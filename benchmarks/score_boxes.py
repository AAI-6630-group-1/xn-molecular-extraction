"""Scoring for datasets with ground-truth boxes on page images (MolMole Patent300).

score.py hands runs on these datasets to score_run() here. Each task follows the
MolMole paper's protocol (LG AI Research, 2025, arXiv:2505.03777, section 3.2.1),
so our numbers line up with its Tables 2 to 4:

- detect: COCO AP and AR averaged over IoU 0.50 to 0.95, and F1 as their harmonic
  mean (MolMole Table 2). We add AP at IoU 0.5 and precision / recall / F1 at
  IoU >= 0.5 with one-to-one matching, as proposed on #14.
- ocsr: one SMILES per ground-truth crop. Exact-match accuracy of canonical
  SMILES, stereo-blind accuracy, and mean Tanimoto (MolMole Table 3). A crop
  with no output, or an invalid one, counts as wrong with similarity 0.
- e2e: boxes with SMILES. A ground-truth molecule is a true positive when the
  predicted box that overlaps it most has IoU >= 0.5 and the same SMILES
  (MolMole equation 1, Table 4). Precision = TP / predicted boxes,
  recall = TP / ground-truth boxes.

Boxes in predictions.csv are x0, y0, x1, y1 in pixels of the page image, origin
at the top left. paper_id is the page image's file stem (for example
AU2004259738B2_page_104), or for ocsr the crop's molfile stem
(AU2004259738B2_page_104_bbox_0).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rdkit import Chem, DataStructs

from score import Molecule, ScoringError, parse

IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)
RECALL_POINTS = np.linspace(0, 1, 101)
MAX_DETS = 100  # COCO's per-image cap; Patent300 has at most 33 molecules per page

DETECT_COLUMNS = [
    "run_id", "handle", "tool", "dataset", "n_pages", "n_gt", "n_pred",
    "ap", "ap50", "ar", "f1_coco", "score_threshold", "n_pred_used", "tp50", "precision50", "recall50", "f1_50",
    "best_f1_50", "best_f1_threshold",
]
OCSR_COLUMNS = [
    "run_id", "handle", "tool", "dataset", "n_gt", "n_output", "n_invalid", "exact",
    "accuracy", "accuracy_stereo_blind", "mean_tanimoto",
]
E2E_COLUMNS = [
    "run_id", "handle", "tool", "dataset", "n_pages", "n_gt", "n_pred", "n_invalid",
    "detected50", "tp", "precision", "recall", "f1",
]
COLUMNS = {"detect": DETECT_COLUMNS, "ocsr": OCSR_COLUMNS, "e2e": E2E_COLUMNS}


@dataclass
class Box:
    page: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 1.0
    molecule: Molecule | None = None
    id: str = ""  # ground truth: <page>_bbox_<n>; predictions: row number


def load_truth(root: Path) -> dict[str, list[Box]]:
    """Read Patent300's structure boxes (category 1) and their molfiles, keyed by page stem."""
    path = root / "json" / "patent_300_huggingface.json"
    if not path.exists():
        raise ScoringError(f"ground truth not found at {path}; see data/README.md")
    pages: dict[str, list[Box]] = {}
    for image in json.loads(path.read_text())["images"]:
        page = Path(image["file_name"]).stem
        pages[page] = []
        for b in image["dla_bboxes"]:
            if b["category_id"] != 1:
                continue
            box_id = f"{page}_bbox_{b['id']}"
            mol = Chem.MolFromMolFile(str(root / "mol" / f"{box_id}.mol"))
            if mol is None:
                raise ScoringError(f"RDKit can't read the ground-truth molfile {box_id}.mol")
            x, y, w, h = b["bbox"]
            pages[page].append(Box(page, x, y, x + w, y + h, molecule=parse(Chem.MolToSmiles(mol)), id=box_id))
    return pages


def _float(row: dict, column: str, path: Path, line: int) -> float:
    try:
        return float(row[column])
    except (KeyError, TypeError, ValueError):
        raise ScoringError(f"{path}:{line}: {column!r} must be a number") from None


def load_boxes(path: Path, pages, need_box: bool, need_smiles: bool) -> dict[str, list[Box]]:
    """Read predictions.csv into boxes per page. An unknown page is an error, not a silent zero."""
    if not path.exists():
        raise ScoringError(f"{path} is missing")
    out: dict[str, list[Box]] = {}
    unknown = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"paper_id"} | ({"x0", "y0", "x1", "y1"} if need_box else set()) | ({"smiles"} if need_smiles else set())
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ScoringError(f"{path} is missing the column(s) {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            page = (row["paper_id"] or "").strip()
            if page not in pages:
                unknown.add(page)
                continue
            coords = [_float(row, c, path, line) for c in ("x0", "y0", "x1", "y1")] if need_box else [0, 0, 0, 0]
            conf = (row.get("confidence") or "").strip()
            smiles = (row.get("smiles") or "").strip()
            out.setdefault(page, []).append(Box(
                page, *coords, score=float(conf) if conf else 1.0,
                molecule=parse(smiles) if smiles else None, id=str(line),
            ))
    if unknown:
        shown = ", ".join(sorted(unknown)[:5]) + (" ..." if len(unknown) > 5 else "")
        raise ScoringError(f"{path}: paper_id(s) not in the ground truth: {shown}")
    return out


def iou_matrix(a: list[Box], b: list[Box]) -> np.ndarray:
    """IoU between every box in a and every box in b, with continuous coordinates (as pycocotools)."""
    if not a or not b:
        return np.zeros((len(a), len(b)))
    A = np.array([[x.x0, x.y0, x.x1, x.y1] for x in a], dtype=float)
    B = np.array([[x.x0, x.y0, x.x1, x.y1] for x in b], dtype=float)
    w = np.clip(np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]), 0, None)
    h = np.clip(np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]), 0, None)
    inter = w * h
    area_a = (A[:, 2] - A[:, 0]) * (A[:, 3] - A[:, 1])
    area_b = (B[:, 2] - B[:, 0]) * (B[:, 3] - B[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)


def _greedy_match(ious: np.ndarray, threshold: float) -> np.ndarray:
    """COCO matching for one page: detections in score order each take the best unmatched GT with IoU >= threshold.

    `ious` is detections x ground truth with detections already sorted by score.
    Returns, for each detection, the matched GT index or -1.
    """
    matched_gt = np.zeros(ious.shape[1], dtype=bool)
    out = np.full(ious.shape[0], -1)
    for d in range(ious.shape[0]):
        best, best_iou = -1, min(threshold, 1 - 1e-10)
        for g in range(ious.shape[1]):
            if matched_gt[g] or ious[d, g] < best_iou:
                continue
            best, best_iou = g, ious[d, g]
        if best >= 0:
            matched_gt[best] = True
            out[d] = best
    return out


def coco_ap_ar(truth: dict[str, list[Box]], preds: dict[str, list[Box]]) -> dict[str, float]:
    """COCO bbox AP and AR (area 'all', maxDets 100), plus AP at IoU 0.5, for one category."""
    n_gt = sum(len(v) for v in truth.values())
    scores, hits = [], [[] for _ in IOU_THRESHOLDS]
    for page, gts in truth.items():
        dets = sorted(preds.get(page, []), key=lambda b: -b.score)[:MAX_DETS]
        ious = iou_matrix(dets, gts)
        scores += [d.score for d in dets]
        for t, threshold in enumerate(IOU_THRESHOLDS):
            hits[t] += list(_greedy_match(ious, threshold) >= 0)
    order = np.argsort(-np.array(scores), kind="mergesort")
    ap, ar = [], []
    for t in range(len(IOU_THRESHOLDS)):
        tp = np.array(hits[t], dtype=float)[order]
        tp_cum, fp_cum = np.cumsum(tp), np.cumsum(1 - tp)
        recall = tp_cum / n_gt if n_gt else np.zeros_like(tp_cum)
        precision = tp_cum / np.maximum(tp_cum + fp_cum, np.finfo(float).eps)
        ar.append(recall[-1] if len(recall) else 0.0)
        envelope = np.maximum.accumulate(precision[::-1])[::-1] if len(precision) else precision
        idx = np.searchsorted(recall, RECALL_POINTS, side="left")
        ap.append(float(np.mean([envelope[i] if i < len(envelope) else 0.0 for i in idx])))
    return {"ap": float(np.mean(ap)), "ap50": ap[0], "ar": float(np.mean(ar))}


def _prf(tp: int, n_pred: int, n_gt: int) -> tuple[float, float, float]:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gt if n_gt else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _match_at_50(truth, preds) -> dict:
    """One-to-one matching at IoU >= 0.5, every box in score order, per page.

    Greedy matching in score order never lets a lower-scoring box change a
    higher-scoring box's match, so the matches with a confidence cut-off are
    the matches of the boxes above it.
    """
    matches = {}
    for page, gts in truth.items():
        dets = sorted(preds.get(page, []), key=lambda b: -b.score)
        ious = iou_matrix(dets, gts)
        matches[page] = (dets, gts, ious, _greedy_match(ious, 0.5))
    return matches


def score_detect(truth, preds, threshold: float) -> tuple[dict, list[dict]]:
    n_gt = sum(len(v) for v in truth.values())
    n_pred = sum(len(v) for v in preds.values())
    coco = coco_ap_ar(truth, preds)
    matches = _match_at_50(truth, preds)
    scored = np.array([d.score for dets, *_ in matches.values() for d in dets])
    hit = np.array([m >= 0 for *_, match in matches.values() for m in match], dtype=bool)

    used = scored >= threshold
    p, r, f1 = _prf(int(hit[used].sum()), int(used.sum()), n_gt)

    # The confidence cut-off with the best F1: what a filter tuned on this set would use.
    best = (0.0, 0.0)
    order = np.argsort(-scored, kind="mergesort")
    tp_cum = np.cumsum(hit[order])
    for k in range(len(order)):
        if k + 1 < len(order) and scored[order[k + 1]] == scored[order[k]]:
            continue  # a cut-off keeps every box with the same score
        best = max(best, (_prf(int(tp_cum[k]), k + 1, n_gt)[2], float(scored[order[k]])))

    row = {
        "n_pages": len(truth), "n_gt": n_gt, "n_pred": n_pred,
        "ap": coco["ap"], "ap50": coco["ap50"], "ar": coco["ar"],
        "f1_coco": 2 * coco["ap"] * coco["ar"] / (coco["ap"] + coco["ar"]) if coco["ap"] + coco["ar"] else 0.0,
        "score_threshold": threshold, "n_pred_used": int(used.sum()), "tp50": int(hit[used].sum()),
        "precision50": p, "recall50": r, "f1_50": f1, "best_f1_50": best[0], "best_f1_threshold": best[1],
    }
    rows = []
    for page, (dets, gts, ious, match) in matches.items():
        kept = np.array([d.score >= threshold for d in dets], dtype=bool)
        for g, gt in enumerate(gts):
            found = bool(np.any((match == g) & kept))
            best_iou = float(ious[:, g].max()) if len(dets) else 0.0
            rows.append({"page": page, "side": "gt", "id": gt.id, "status": "TP" if found else "FN",
                         "iou": f"{best_iou:.4f}", "score": "", **_coords(gt)})
        for d, det in enumerate(dets):
            best_iou = float(ious[d].max()) if len(gts) else 0.0
            status = ("TP" if match[d] >= 0 else "FP") if kept[d] else "below_threshold"
            rows.append({"page": page, "side": "pred", "id": det.id, "status": status,
                         "iou": f"{best_iou:.4f}", "score": f"{det.score:.4f}", **_coords(det)})
    return row, rows


def _coords(b: Box) -> dict:
    return {"x0": round(b.x0, 1), "y0": round(b.y0, 1), "x1": round(b.x1, 1), "y1": round(b.y1, 1)}


def _tanimoto(a: Molecule, b: Molecule | None) -> float:
    if b is None or not b.valid:
        return 0.0
    return DataStructs.TanimotoSimilarity(a.fingerprint, b.fingerprint)


def load_crop_predictions(path: Path, crop_ids) -> dict[str, str]:
    """Read an ocsr run's predictions.csv into {crop ID: SMILES as the tool wrote it}.

    Crops with an empty SMILES are left out (no output). An unknown crop ID, or
    two rows for one crop, is an error rather than a silent zero.
    """
    if not path.exists():
        raise ScoringError(f"{path} is missing")
    preds: dict[str, str] = {}
    seen, unknown = set(), set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"paper_id", "smiles"} - set(reader.fieldnames or [])
        if missing:
            raise ScoringError(f"{path} is missing the column(s) {', '.join(sorted(missing))}")
        for row in reader:
            crop, smiles = (row["paper_id"] or "").strip(), (row["smiles"] or "").strip()
            if crop not in crop_ids:
                unknown.add(crop)
            elif crop in seen:
                raise ScoringError(f"{path}: more than one SMILES for {crop}; an ocsr run gives one per image")
            seen.add(crop)
            if smiles and crop in crop_ids:
                preds[crop] = smiles
    if unknown:
        raise ScoringError(f"{path}: paper_id(s) not in the ground truth: {', '.join(sorted(unknown)[:5])}")
    return preds


def score_crops(truth: dict[str, Molecule], preds: dict[str, Molecule]) -> tuple[dict, list[dict]]:
    """Score one SMILES per crop against its ground truth: exact, stereo-blind, and Tanimoto (MolMole Table 3)."""
    rows, exact, blind, sims = [], 0, 0, []
    for crop, gt in truth.items():
        pred = preds.get(crop)
        is_exact = pred is not None and gt.valid and pred.key == gt.key
        is_blind = pred is not None and pred.valid and gt.valid and pred.stereo_blind == gt.stereo_blind
        sim = _tanimoto(gt, pred) if gt.valid else 0.0
        exact, blind = exact + is_exact, blind + is_blind
        sims.append(sim)
        rows.append({"crop": crop, "status": "correct" if is_exact else ("no_output" if pred is None else "wrong"),
                     "stereo_blind_match": is_blind, "tanimoto": f"{sim:.4f}", "gt_smiles": gt.smiles,
                     "pred_smiles": pred.smiles if pred else ""})
    n = len(truth)
    row = {
        "n_gt": n, "n_output": len(preds), "n_invalid": sum(not p.valid for p in preds.values()), "exact": exact,
        "accuracy": exact / n if n else 0.0, "accuracy_stereo_blind": blind / n if n else 0.0,
        "mean_tanimoto": float(np.mean(sims)) if sims else 0.0,
    }
    return row, rows


def score_ocsr(truth, path: Path) -> tuple[dict, list[dict]]:
    crops = {b.id: b.molecule for boxes in truth.values() for b in boxes}
    preds = {crop: parse(smiles) for crop, smiles in load_crop_predictions(path, crops).items()}
    return score_crops(crops, preds)


def score_e2e(truth, preds) -> tuple[dict, list[dict]]:
    """MolMole equation 1: each GT box is checked against the predicted box that overlaps it most."""
    n_gt = sum(len(v) for v in truth.values())
    n_pred = sum(len(v) for v in preds.values())
    tp = detected = 0
    rows = []
    for page, gts in truth.items():
        dets = preds.get(page, [])
        ious = iou_matrix(gts, dets)
        for g, gt in enumerate(gts):
            j = int(ious[g].argmax()) if dets else -1
            iou = float(ious[g, j]) if dets else 0.0
            pred = dets[j].molecule if dets else None
            hit_box = iou >= 0.5
            correct = hit_box and pred is not None and pred.key == gt.molecule.key
            detected += hit_box
            tp += correct
            rows.append({"page": page, "gt_id": gt.id, "status": "TP" if correct else "FN", "iou": f"{iou:.4f}",
                         "pred_id": dets[j].id if dets else "", "gt_smiles": gt.molecule.smiles,
                         "pred_smiles": pred.smiles if pred else "",
                         "tanimoto": f"{_tanimoto(gt.molecule, pred):.4f}" if hit_box else ""})
    p, r, f1 = _prf(tp, n_pred, n_gt)
    row = {
        "n_pages": len(truth), "n_gt": n_gt, "n_pred": n_pred,
        "n_invalid": sum(b.molecule is not None and not b.molecule.valid for v in preds.values() for b in v),
        "detected50": detected, "tp": tp, "precision": p, "recall": r, "f1": f1,
    }
    return row, rows


def score_run(run_dir: Path, run: dict, root: Path, score_threshold: float = 0.0) -> tuple[list[str], list[dict]]:
    """Score one box-dataset run; writes scores.csv and matches.csv and returns (columns, [score row])."""
    truth = load_truth(root)
    task = run["task"]
    if task == "detect":
        row, matches = score_detect(truth, load_boxes(run_dir / "predictions.csv", truth, True, False), score_threshold)
    elif task == "ocsr":
        row, matches = score_ocsr(truth, run_dir / "predictions.csv")
    elif task == "e2e":
        row, matches = score_e2e(truth, load_boxes(run_dir / "predictions.csv", truth, True, True))
    else:
        raise ScoringError(f"{run_dir}: unknown task {task!r}; use detect, ocsr, or e2e")
    row = {**{k: run[k] for k in ("run_id", "handle", "tool", "dataset")},
           **{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in row.items()}}
    _write(run_dir / "scores.csv", COLUMNS[task], [row])
    if matches:
        _write(run_dir / "matches.csv", list(matches[0]), matches)
    return COLUMNS[task], [row]


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
