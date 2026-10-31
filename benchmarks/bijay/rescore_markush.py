#!/usr/bin/env python3
"""Rescore the BioVista Markush crops with each reader's R-group placeholder rewritten as `*`.

    uv run python benchmarks/bijay/rescore_markush.py

BioVista writes every R-group as `*`, and none of DECIMER's, MolGrapher's or DeepSeek-OCR-2's outputs contains
one, so their Markush score is 0% by construction (README). This reads the raw predictions in each run's
committed matches.csv, rewrites the placeholder the reader uses in its place, and scores the result with the
team's canonicalizer (score.parse), so no model is rerun and it needs only RDKit and numpy (CPU, seconds).

The rules were chosen on BioVista's validation split (33 papers, 855 crops) and then applied unchanged to the
test split (302 papers, 8,006 crops). A rule applies to every output, not only to Markush crops, so the tables
also show what it costs on crops without R-groups. The committed scores are not changed.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # benchmarks/, for score.py

from rdkit import DataStructs  # noqa: E402

from score import parse  # noqa: E402

RESULTS = HERE.parent / "results" / "ArkAngel101"
RUNS = {
    "DECIMER": "2026-10-18_decimer_biovista",
    "MolGrapher": "2026-10-19_molgrapher_biovista",
    "DeepSeek-OCR-2": "2026-10-19_deepseek_ocr2_biovista",
}

# Conventional Markush variable names written as bracket atoms ([R], [R1], [R17a], [X], [Y], [Z]); RDKit
# rejects them, so DECIMER's outputs with one count as invalid.
LABEL = re.compile(r"\[(?:R\d*[a-z]?|X|Y|Z)\]")
BORON = re.compile(r"\[B\]|B(?![a-z])")  # MolGrapher's stand-in for an R-group; the lookahead spares Br
HYDROGEN = re.compile(r"\[H\]")

CANDIDATES = {
    "none": lambda s: s,
    "labels": lambda s: LABEL.sub("*", s),
    "boron": lambda s: BORON.sub("*", s),
    "hydrogen": lambda s: HYDROGEN.sub("*", s),
    "labels+boron+hydrogen": lambda s: HYDROGEN.sub("*", BORON.sub("*", LABEL.sub("*", s))),
}
# The rule each reader keeps, from the validation table. Boron helps MolGrapher on the whole split, while
# [H] loses more crops without R-groups than it recovers, and nothing helps DeepSeek-OCR-2.
CHOSEN = {"DECIMER": "labels", "MolGrapher": "boron", "DeepSeek-OCR-2": "none"}


def load(name: str, split: str) -> list[dict]:
    with open(RESULTS / RUNS[name] / "matches.csv", newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row["split"] == split]


def subsets(row: dict) -> list[str]:
    """`structure` is e.g. "markush; chiral"; every crop counts in all, and in full or markush."""
    kinds = ["all", "markush" if "markush" in row["structure"] else "full"]
    return kinds + (["chiral"] if "chiral" in row["structure"] else [])


def evaluate(rows: list[dict], rule) -> dict[str, dict[str, float]]:
    """Exact match, stereo-blind match, Tanimoto and invalid count per subset, as score.py defines them."""
    totals = {k: {"n": 0, "exact": 0, "blind": 0, "tanimoto": 0.0, "invalid": 0} for k in ("all", "full", "chiral", "markush")}
    for row in rows:
        truth, pred = parse(row["gt_smiles"]), parse(rule(row["pred_smiles_raw"] or ""))
        invalid = pred.key.startswith("invalid:")
        exact = not invalid and pred.key == truth.key
        blind = not invalid and truth.stereo_blind is not None and pred.stereo_blind == truth.stereo_blind
        tanimoto = 0.0
        if not invalid and truth.fingerprint is not None:
            tanimoto = DataStructs.TanimotoSimilarity(pred.fingerprint, truth.fingerprint)
        for kind in subsets(row):
            t = totals[kind]
            t["n"] += 1
            t["exact"] += exact
            t["blind"] += blind
            t["tanimoto"] += tanimoto
            t["invalid"] += invalid
    return totals


def main() -> int:
    print("Validation split: exact matches per candidate rule (n = 855 crops: 434 without R-groups, 421 Markush)")
    print(f"{'reader':16s}{'rule':24s}{'all':>6s}{'no R-group':>12s}{'Markush':>9s}")
    for name in RUNS:
        rows = load(name, "valid")
        for label, rule in CANDIDATES.items():
            t = evaluate(rows, rule)
            mark = "  <- kept" if CHOSEN[name] == label else ""
            print(f"{name:16s}{label:24s}{t['all']['exact']:6d}{t['full']['exact']:12d}{t['markush']['exact']:9d}{mark}")

    print("\nTest split: committed raw outputs, then with the kept rule (n = 8,006 crops)")
    print(f"{'reader':16s}{'subset':9s}{'n':>6s}{'exact before':>14s}{'exact after':>13s}{'Tanimoto':>18s}{'stereo-blind':>18s}{'invalid':>12s}")
    for name in RUNS:
        rows = load(name, "test")
        before, after = evaluate(rows, CANDIDATES["none"]), evaluate(rows, CANDIDATES[CHOSEN[name]])
        for kind in ("all", "full", "chiral", "markush"):
            b, a, n = before[kind], after[kind], before[kind]["n"]
            print(f"{name:16s}{kind:9s}{n:6d}{b['exact'] / n:14.1%}{a['exact'] / n:13.1%}"
                  f"{b['tanimoto'] / n:9.3f} ->{a['tanimoto'] / n:6.3f}{b['blind'] / n:9.1%} ->{a['blind'] / n:6.1%}"
                  f"{b['invalid']:7d} ->{a['invalid']:4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
