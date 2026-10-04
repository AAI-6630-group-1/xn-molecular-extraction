#!/usr/bin/env python3
"""Break a scored Track 3 run down by error type, for the 1.3 report.

    uv run python benchmarks/willdaly/analyze_track3.py benchmarks/results/willdaly/<run_id>

Reads predictions.csv and matches.csv (run score.py first) and prints two
Markdown tables:

- Boxes: what each MolDetV2 box became. Every box lands in exactly one column,
  checked in this order: no output, invalid SMILES, R-group scaffold (a `*`
  atom, so a Markush drawing read without its table), several fragments (stray
  label text or a salt), correct, or wrong.
- Misses: why each ground-truth molecule was missed. Stereo only (right graph,
  wrong wedges), near miss (best Tanimoto >= 0.8), or not found. "Largest
  fragment" is recall if every prediction kept only its biggest fragment, which
  rescues stray-text outputs but would strip salts the ground truth keeps.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score import paper_key, parse  # noqa: E402

BOX_COLUMNS = ["no_output", "invalid", "rgroup", "multi_fragment", "correct", "wrong"]
NEAR_MISS = 0.8


def read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def largest_fragment_key(smiles: str) -> str | None:
    mol = parse(smiles)
    if not mol.valid:
        return None
    frags = Chem.GetMolFrags(Chem.MolFromSmiles(mol.smiles), asMols=True)
    return parse(Chem.MolToSmiles(max(frags, key=lambda m: m.GetNumHeavyAtoms()))).key


def classify_box(smiles: str, truth_keys: set[str]) -> str:
    smiles = smiles.strip()
    if not smiles:
        return "no_output"
    mol = parse(smiles)
    if not mol.valid:
        return "invalid"
    if mol.key in truth_keys:
        return "correct"  # a correct molecule can still contain '.', e.g. a salt
    if "*" in mol.smiles:
        return "rgroup"
    if "." in mol.smiles:
        return "multi_fragment"
    return "wrong"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    args = ap.parse_args()

    preds = read(args.run_dir / "predictions.csv")
    matches = read(args.run_dir / "matches.csv")
    gt = [m for m in matches if m["side"] == "gt"]
    truth_keys = defaultdict(set)
    for m in gt:
        truth_keys[m["paper_id"]].add(m["smiles"])
    papers = sorted(truth_keys, key=int)

    boxes = {p: Counter() for p in papers}
    largest = defaultdict(set)
    for row in preds:
        paper = paper_key(row["paper_id"])
        boxes[paper][classify_box(row["smiles"], truth_keys[paper])] += 1
        key = largest_fragment_key(row["smiles"]) if row["smiles"].strip() else None
        if key:
            largest[paper].add(key)

    print("Boxes: what each MolDetV2 box became\n")
    print("| Paper | Boxes | " + " | ".join(c.replace("_", " ").capitalize() for c in BOX_COLUMNS) + " |")
    print("|---" * (len(BOX_COLUMNS) + 2) + "|")
    total = Counter()
    for p in papers:
        total.update(boxes[p])
        print(f"| {p} | {sum(boxes[p].values())} | " + " | ".join(str(boxes[p][c]) for c in BOX_COLUMNS) + " |")
    print(f"| All | {sum(total.values())} | " + " | ".join(str(total[c]) for c in BOX_COLUMNS) + " |")

    print("\nMisses: why each ground-truth molecule was missed\n")
    print("| Paper | Molecules | Found | Stereo only | Near miss | Not found | Largest fragment |")
    print("|---|---|---|---|---|---|---|")
    total = Counter()
    for p in papers:
        rows = [m for m in gt if m["paper_id"] == p]
        c = Counter()
        for m in rows:
            if m["status"] == "TP":
                c["found"] += 1
            elif m["stereo_blind_match"] == "True":
                c["stereo"] += 1
            elif m["best_tanimoto"] and float(m["best_tanimoto"]) >= NEAR_MISS:
                c["near"] += 1
            else:
                c["not_found"] += 1
        c["n"] = len(rows)
        c["largest"] = len(truth_keys[p] & largest[p])
        total.update(c)
        print(f"| {p} | {c['n']} | {c['found']} | {c['stereo']} | {c['near']} | {c['not_found']} | {c['largest']} |")
    print(f"| All | {total['n']} | {total['found']} | {total['stereo']} | {total['near']} | {total['not_found']} "
          f"| {total['largest']} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
