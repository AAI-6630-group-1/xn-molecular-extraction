"""Scoring for BioVista's OCSR task: one molecule crop in, one SMILES out.

score.py hands runs with "dataset": "biovista" to score_run() here. BioVista
(Yan et al., 2026, arXiv:2604.21508) ships 8,861 crops from 335 papers, each
with one ground-truth SMILES in ocsr/labels/gd_SMIELS.csv; 45% are Markush
scaffolds whose R-groups are `*` atoms.

Every crop gets the same three numbers as Patent300's ocsr task (see
score_boxes.score_crops): exact match of canonical SMILES as score.py
canonicalizes them (R-group labels ignored, so `*`, `[1*]` and `[*:1]` are the
same atom), stereo-blind match, and Tanimoto similarity. A fourth column applies
BioVista's own match rule (biovista_match below), so our numbers can be set
next to the BioMiner paper's OCSR table.

Scores are broken down two ways, as in BioMiner's table:
- subset: every crop, and BioVista's test split (302 papers, 8,006 crops; the
  other 33 papers are its validation split). The split lists come from the
  BioMiner repository (see benchmarks/willdaly/download_data.py).
- structure: full (no R-group), chiral (has a stereocentre, `@`), markush (has
  an R-group, `*`), and all. Chiral overlaps the other two.

predictions.csv has one row per crop. paper_id is the crop's file stem, for
example 51_6rrm_image_molminer_bbox_3-0 (paper 51_6rrm, page 3, crop 0). A crop
with no row counts as no output, unless run.json sets "crop_sample": true: then
the run read a sample of the crops, and only the crops listed in
predictions.csv (an empty smiles still counts as no output) are scored.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rdkit import Chem

from score import Molecule, ScoringError, parse
from score_boxes import load_crop_predictions, score_crops

LABELS = Path("ocsr") / "labels" / "gd_SMIELS.csv"
CROPS = Path("ocsr") / "data"
SPLITS = {"test": "test_set_names.txt", "valid": "valid_set_names.txt"}
STRUCTURES = ("all", "full", "chiral", "markush")
COLUMNS = [
    "run_id", "handle", "tool", "dataset", "subset", "structure", "n_gt", "n_output", "n_invalid", "exact",
    "accuracy", "accuracy_stereo_blind", "mean_tanimoto", "biovista_match", "accuracy_biovista",
]

# Charged atoms that neutralize_smiles in BioMiner's process_mol.py resets to neutral.
_CHARGED = Chem.MolFromSmarts("[+1!h0!$([*]~[-1,-2,-3,-4]),-1!$([*]~[+1,+2,+3,+4])]")


@dataclass
class Crop:
    id: str
    paper: str  # BioVista's pdf_name, e.g. 51_6rrm
    smiles: str  # ground truth as BioVista wrote it
    molecule: Molecule
    split: str  # test, valid, or "" if the split lists are missing

    def structures(self) -> list[str]:
        out = ["all", "markush" if "*" in self.smiles else "full"]
        return out + (["chiral"] if "@" in self.smiles else [])


def crop_key(stem: str) -> tuple[str, int]:
    """(pdf_name, index) from a crop's file stem: 51_6rrm_image_molminer_bbox_3-0 -> ('51_6rrm', 0)."""
    parts = stem.split("_")
    return f"{parts[0]}_{parts[1]}", int(parts[-1].split("-")[1])


def load_truth(root: Path) -> dict[str, Crop]:
    """Join BioVista's label table to its crop files on (pdf_name, index).

    The labels CSV isn't in crop-file order, so the join is on the key rather
    than on row position.
    """
    labels_path, crop_dir = root / LABELS, root / CROPS
    if not labels_path.exists() or not crop_dir.is_dir():
        raise ScoringError(f"BioVista OCSR set not found under {root}; run benchmarks/willdaly/download_data.py")
    with open(labels_path, newline="", encoding="utf-8") as f:
        labels = {(row["pdf_name"], int(row["index"])): row["smiles"] for row in csv.DictReader(f)}
    split_of = {}
    for split, name in SPLITS.items():
        if (root / name).exists():
            split_of.update({paper: split for paper in (root / name).read_text().split()})

    truth = {}
    for path in sorted(crop_dir.glob("*.png")):
        key = crop_key(path.stem)
        if key not in labels:
            raise ScoringError(f"no ground-truth SMILES for crop {path.name}")
        smiles = labels[key]
        # One label (a BODIPY dye with a dative B~N bond) doesn't parse in RDKit; it stays in the denominator.
        truth[path.stem] = Crop(path.stem, key[0], smiles, parse(smiles), split_of.get(key[0], ""))
    if len(truth) != len(labels):
        raise ScoringError(f"{len(labels)} labels but {len(truth)} crops in {crop_dir}")
    return truth


def _neutralize(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    for (idx,) in mol.GetSubstructMatches(_CHARGED):
        atom = mol.GetAtomWithIdx(idx)
        charge, hydrogens = atom.GetFormalCharge(), atom.GetTotalNumHs()
        atom.SetFormalCharge(0)
        atom.SetNumExplicitHs(hydrogens - charge)
        atom.UpdatePropertyCache()
    return Chem.MolToSmiles(mol)


def _unlabel_first_r1(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return smiles
    for atom in mol.GetAtoms():
        if atom.GetSymbol() == "*" and atom.GetIsotope() == 1:
            atom.SetIsotope(0)
            break
    return Chem.MolToSmiles(mol)


def biovista_match(pred: str | None, gt: str) -> bool:
    """BioVista's match rule, from check_smiles_match in BioMiner's process_mol.py (commit 17c6161).

    Both SMILES are neutralized and canonicalized, and the first R-group atom
    labelled 1 loses its label. Unlike score.py, other R-group labels must
    match, so `[2*]` and `*` differ, while charge states are forgiven.
    """
    if not pred:
        return False
    try:
        a = Chem.MolToSmiles(Chem.MolFromSmiles(_neutralize(pred)))
        b = Chem.MolToSmiles(Chem.MolFromSmiles(_neutralize(gt)))
        return _unlabel_first_r1(a) == _unlabel_first_r1(b)
    except Exception:  # BioMiner counts anything RDKit rejects as a miss
        return False


def summarize(crops: list[Crop], rows: dict[str, dict]) -> dict:
    """Metrics over one group of crops, from the per-crop rows."""
    n = len(crops)
    group = [rows[c.id] for c in crops]
    exact = sum(r["status"] == "correct" for r in group)
    bv = sum(r["biovista_match"] for r in group)
    return {
        "n_gt": n, "n_output": sum(r["status"] != "no_output" for r in group),
        "n_invalid": sum(r["output_valid"] is False for r in group), "exact": exact,
        "accuracy": exact / n if n else 0.0,
        "accuracy_stereo_blind": sum(r["stereo_blind_match"] for r in group) / n if n else 0.0,
        "mean_tanimoto": float(np.mean([float(r["tanimoto"]) for r in group])) if group else 0.0,
        "biovista_match": bv, "accuracy_biovista": bv / n if n else 0.0,
    }


def score_run(run_dir: Path, run: dict, root: Path) -> tuple[list[str], list[dict]]:
    """Score one BioVista ocsr run; writes scores.csv and matches.csv and returns (columns, score rows)."""
    if run["task"] != "ocsr":
        raise ScoringError(f"{run_dir}: BioVista runs are scored as ocsr, not {run['task']!r}")
    truth = load_truth(root)
    if run.get("crop_sample"):
        with open(run_dir / "predictions.csv", newline="", encoding="utf-8-sig") as f:
            listed = {(row.get("paper_id") or "").strip() for row in csv.DictReader(f)}
        truth = {k: v for k, v in truth.items() if k in listed}
    raw = load_crop_predictions(run_dir / "predictions.csv", truth)
    parsed = {i: parse(s) for i, s in raw.items()}
    _, crop_rows = score_crops({c.id: c.molecule for c in truth.values()}, parsed)
    rows = {}
    for r in crop_rows:
        crop = truth[r["crop"]]
        rows[crop.id] = {"crop": crop.id, "paper": crop.paper, "split": crop.split,
                         "structure": "; ".join(crop.structures()[1:]), **{k: v for k, v in r.items() if k != "crop"},
                         "output_valid": parsed[crop.id].valid if crop.id in parsed else "",
                         "biovista_match": biovista_match(raw.get(crop.id), crop.smiles),
                         "gt_smiles_biovista": crop.smiles, "pred_smiles_raw": raw.get(crop.id, "")}

    scores = []
    subsets = {"all": list(truth.values()), "test": [c for c in truth.values() if c.split == "test"]}
    for subset, crops in subsets.items():
        if not crops:
            continue  # no split lists downloaded
        for structure in STRUCTURES:
            group = [c for c in crops if structure in c.structures()]
            metrics = summarize(group, rows)
            scores.append({**{k: run[k] for k in ("run_id", "handle", "tool", "dataset")},
                           "subset": subset, "structure": structure,
                           **{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in metrics.items()}})
    _write(run_dir / "scores.csv", COLUMNS, scores)
    _write(run_dir / "matches.csv", list(next(iter(rows.values()))), list(rows.values()))
    return COLUMNS, scores


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
