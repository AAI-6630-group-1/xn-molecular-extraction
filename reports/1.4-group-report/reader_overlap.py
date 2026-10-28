"""Compare MolGlyph, MolScribe, MolSight and MolNexTR on the same BioVista crops (XN 1.4).

Peter's MolNexTR run covers a seeded sample of 1,000 of the 8,861 BioVista OCSR
crops; the other three runs cover all of them. This script reads each run's
committed matches.csv (written by benchmarks/score.py), keeps the 1,000 shared
crops, and reports:
- exact matches overall and on chiral crops;
- how often each reader works as MolGlyph's second vote (keep MolGlyph's answer
  only when the second reader returns the same canonical SMILES);
- on chiral crops where both readers got the skeleton right, how often only one
  of them also got the stereochemistry right.

Run from the repo root (CPU, about a second):
    uv run python reports/1.4-group-report/reader_overlap.py
"""
from __future__ import annotations

import csv
import itertools
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "benchmarks/results"
RUNS = {
    "MolGlyph": RESULTS / "willdaly/2026-10-06_molglyph_biovista",
    "MolScribe": RESULTS / "willdaly/2026-10-06_molscribe_biovista",
    "MolSight": RESULTS / "liba-jin/2026-10-13_molsight-extra_biovista",
    "MolNexTR": RESULTS / "PeterAdr14/2026-10-15_molnextr_biovista",
}
OUT = Path(__file__).with_suffix(".txt")


def load(run_dir: Path) -> dict[str, dict]:
    with open(run_dir / "matches.csv", newline="", encoding="utf-8") as f:
        return {row["crop"]: row for row in csv.DictReader(f)}


def main() -> None:
    m = {name: load(path) for name, path in RUNS.items()}
    sample = sorted(m["MolNexTR"])
    exact = lambda r, c: m[r][c]["status"] == "correct"
    skeleton = lambda r, c: m[r][c]["stereo_blind_match"] == "True"
    chiral = [c for c in sample if "chiral" in m["MolGlyph"][c]["structure"]]

    lines = [f"{len(sample)} shared crops, {len(chiral)} chiral", "",
             "reader | exact (all) | exact (chiral) | as MolGlyph's second vote: kept, correct, precision"]
    for r in RUNS:
        vote = "n/a"
        if r != "MolGlyph":
            kept = [c for c in sample if m["MolGlyph"][c]["pred_smiles"]
                    and m["MolGlyph"][c]["pred_smiles"] == m[r][c]["pred_smiles"]]
            right = sum(exact("MolGlyph", c) for c in kept)
            vote = f"{len(kept)}, {right}, {right / len(kept):.1%}"
        lines.append(f"{r} | {sum(exact(r, c) for c in sample)} | {sum(exact(r, c) for c in chiral)} | {vote}")

    lines += ["", "chiral crops with both skeletons right: n, only A has stereo right, only B has stereo right"]
    for a, b in itertools.combinations(RUNS, 2):
        both = [c for c in chiral if skeleton(a, c) and skeleton(b, c)]
        lines.append(f"{a} vs {b} | {len(both)} | {sum(exact(a, c) and not exact(b, c) for c in both)}"
                     f" | {sum(exact(b, c) and not exact(a, c) for c in both)}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
