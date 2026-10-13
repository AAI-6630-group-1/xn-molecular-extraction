#!/usr/bin/env python3
"""Track 3 on MolMole Patent300: MolDetV2 detection, recognition, and both together.

Writes up to three runs for benchmarks/score.py, one per MolMole evaluation:

- detect: MolDetV2 boxes on all 300 page images. Boxes down to --min-conf are kept
  so AP covers the whole precision-recall curve; run.json's score_threshold
  (--conf) is the operating point for precision and recall.
- ocsr: the reader (MolScribe or MolGlyph, see benchmarks/readers.py) on every ground-truth
  box (2,482 crops), so recognition is scored without detection errors.
- e2e: the reader on the MolDetV2 boxes scoring >= --conf, the pipeline that
  run_track3.py runs on the internal papers.

    uv run python benchmarks/willdaly/run_patent300.py
    uv run python benchmarks/willdaly/run_patent300.py --tasks ocsr --ocsr-pad 10 --ocsr-tool molscribe-pad10
    uv run python benchmarks/willdaly/run_patent300.py --reader molglyph --tasks ocsr e2e --pad 0
    uv run python benchmarks/score.py benchmarks/results/willdaly/<run_id>

Needs Patent300 in data/patent300/ (see data/README.md).
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
from huggingface_hub import hf_hub_download
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "data" / "patent300"
sys.path.insert(0, str(HERE.parent))  # shared code: readers.py, molglyph.py
sys.path.insert(0, str(HERE))
from readers import READERS, load_reader  # noqa: E402
from run_track3 import git_commit, hardware, versions  # noqa: E402


def gt_boxes() -> list[tuple[str, str, list[float]]]:
    """(page stem, crop id, [x0, y0, x1, y1]) for every structure box in Patent300."""
    out = []
    for image in json.loads((DATA / "json" / "patent_300_huggingface.json").read_text())["images"]:
        page = Path(image["file_name"]).stem
        for b in image["dla_bboxes"]:
            if b["category_id"] == 1:
                x, y, w, h = b["bbox"]
                out.append((page, f"{page}_bbox_{b['id']}", [x, y, x + w, y + h]))
    return out


def crop(img: np.ndarray, box, pad: int) -> np.ndarray:
    h, w, _ = img.shape
    x0, y0, x1, y1 = box
    return img[max(0, int(y0) - pad):min(h, int(np.ceil(y1)) + pad), max(0, int(x0) - pad):min(w, int(np.ceil(x1)) + pad)]


def write_run(run_id: str, tool: str, task: str, rows: list[dict], columns: list[str], args, pipeline: str,
              runtime_s: float, settings: dict, extra: dict | None = None, reader_versions: dict | None = None) -> None:
    run_dir = REPO / "benchmarks" / "results" / "willdaly" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "predictions.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    run = {
        "handle": "willdaly", "tool": tool, "track": 3, "task": task, "dataset": "patent300",
        "pipeline": pipeline, "settings": settings, **(extra or {}),
        "versions": {**versions(), **(reader_versions or {})},
        "command": "uv run python " + " ".join(shlex.quote(a) for a in [
            str(Path(sys.argv[0]).resolve().relative_to(REPO)), *sys.argv[1:]]),
        "git_commit": git_commit(), "hardware": f"{hardware()}, {args.device}",
        "runtime_s": {"all": round(runtime_s, 1)}, "api_cost_usd": None, "notes": args.notes,
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    print(f"wrote {run_dir.relative_to(REPO)} ({len(rows)} rows, {runtime_s:.0f} s)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", nargs="+", default=["detect", "ocsr", "e2e"], choices=["detect", "ocsr", "e2e"])
    ap.add_argument("--conf", type=float, default=0.5, help="MolDetV2 operating point (model card uses 0.5)")
    ap.add_argument("--min-conf", type=float, default=0.01, help="lowest MolDetV2 score kept for the detect run")
    ap.add_argument("--reader", choices=READERS, default="molscribe", help="recognizer for the ocsr and e2e runs")
    ap.add_argument("--pad", type=int, default=10, help="pixels around each detected box before recognition (e2e)")
    ap.add_argument("--ocsr-pad", type=int, default=0,
                    help="pixels around each ground-truth box (ocsr); MolMole crops the box as annotated")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--detect-tool", default="moldetv2")
    ap.add_argument("--ocsr-tool", help="default: <reader>")
    ap.add_argument("--e2e-tool", help="default: moldetv2-<reader>")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--notes", default="")
    args = ap.parse_args()
    args.ocsr_tool = args.ocsr_tool or args.reader
    args.e2e_tool = args.e2e_tool or f"moldetv2-{args.reader}"

    pages = sorted(p.stem for p in (DATA / "images_300").glob("*.png"))
    if len(pages) != 300:
        sys.exit(f"expected 300 page images in {DATA / 'images_300'}, found {len(pages)}; see data/README.md")

    def load(page: str) -> np.ndarray:
        return np.asarray(Image.open(DATA / "images_300" / f"{page}.png").convert("RGB"))

    reader = load_reader(args.reader, args.device) if {"ocsr", "e2e"} & set(args.tasks) else None

    detections = []  # (page, [x0, y0, x1, y1], score)
    if {"detect", "e2e"} & set(args.tasks):
        from ultralytics import YOLO
        detector = YOLO(hf_hub_download("UniParser/MolDetv2", "moldet_v2_yolo11n_960_doc.pt"))
        t0 = time.perf_counter()
        for page in pages:
            # Ultralytics treats numpy input as BGR, so flip the channels.
            result = detector.predict(load(page)[..., ::-1], imgsz=960, conf=args.min_conf, max_det=300,
                                      device=args.device, verbose=False)[0]
            detections += [(page, xyxy, s) for xyxy, s in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist())]
        detect_s = time.perf_counter() - t0

    if "detect" in args.tasks:
        rows = [{"paper_id": page, "x0": round(b[0], 1), "y0": round(b[1], 1), "x1": round(b[2], 1),
                 "y1": round(b[3], 1), "confidence": round(s, 4)} for page, b, s in detections]
        write_run(f"{args.date}_{args.detect_tool}_patent300", args.detect_tool, "detect", rows,
                  ["paper_id", "x0", "y0", "x1", "y1", "confidence"], args,
                  f"MolDetV2 (960 px doc model) on each page image, boxes with score >= {args.min_conf}",
                  detect_s, {"imgsz": 960, "min_conf": args.min_conf, "max_det": 300},
                  {"score_threshold": args.conf})

    if "ocsr" in args.tasks:
        t0 = time.perf_counter()
        boxes = gt_boxes()
        rows, cache = [], {}
        for page in pages:
            page_boxes = [(cid, b) for p, cid, b in boxes if p == page]
            if not page_boxes:
                continue
            img = load(page)
            preds = reader.predict([crop(img, b, args.ocsr_pad) for _, b in page_boxes])
            rows += [{"paper_id": cid, "smiles": p["smiles"], "confidence": round(p["confidence"], 4)}
                     for (cid, _), p in zip(page_boxes, preds)]
        write_run(f"{args.date}_{args.ocsr_tool}_patent300", args.ocsr_tool, "ocsr", rows,
                  ["paper_id", "smiles", "confidence"], args,
                  f"{args.reader} on each ground-truth box, cropped with a {args.ocsr_pad} px margin",
                  time.perf_counter() - t0, {"pad_px": args.ocsr_pad, "reader": args.reader},
                  reader_versions=reader.versions)

    if "e2e" in args.tasks:
        t0 = time.perf_counter()
        rows = []
        for page in pages:
            page_dets = [(b, s) for p, b, s in detections if p == page and s >= args.conf]
            if not page_dets:
                continue
            img = load(page)
            preds = reader.predict([crop(img, b, args.pad) for b, _ in page_dets])
            rows += [{"paper_id": page, "smiles": p["smiles"], "x0": round(b[0], 1), "y0": round(b[1], 1),
                      "x1": round(b[2], 1), "y1": round(b[3], 1), "confidence": round(p["confidence"], 4),
                      "det_confidence": round(s, 4)} for (b, s), p in zip(page_dets, preds)]
        write_run(f"{args.date}_{args.e2e_tool}_patent300", args.e2e_tool, "e2e", rows,
                  ["paper_id", "smiles", "x0", "y0", "x1", "y1", "confidence", "det_confidence"], args,
                  f"MolDetV2 boxes with score >= {args.conf} -> crop with {args.pad} px margin -> {args.reader}",
                  time.perf_counter() - t0 + detect_s,
                  {"det_conf": args.conf, "pad_px": args.pad, "imgsz": 960, "reader": args.reader},
                  reader_versions=reader.versions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
