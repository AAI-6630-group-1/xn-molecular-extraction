"""Worked example for the R-group assembly module (XN 1.4, Will's section).

MolGlyph often reads a scaffold and its substituent as separate drawings, each
with one `*` attachment point. This script joins every same-page pair of
one-attachment fragments from the committed MolDetV2 + MolGlyph run and checks
the joined molecules against the answer key.

The answer key is used only to count which joins would be correct. That makes
the "new answer-key molecules" figure an upper bound for a perfect pairing
step, not a pipeline result: the real module must choose pairs from label and
table evidence and abstain when it has none.

Run from the repo root (CPU, a few seconds):
    uv run python reports/1.4-group-report/assembly_example.py
"""
from __future__ import annotations

import csv
import itertools
from pathlib import Path

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "benchmarks/results/willdaly/2026-10-06_moldetv2-molglyph-pad0_internal/predictions.csv"
GT = REPO / "data/internal/ground_truth_SMILES_confirmed_1,2,4,6,16,19.csv"
OUT = Path(__file__).with_suffix(".txt")
PAPERS = ["1", "2", "4", "6", "16", "19"]


def canon(smiles: str | None) -> str | None:
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return Chem.MolToSmiles(mol) if mol else None


def one_attachment(smiles: str):
    """Return the molecule if it has exactly one `*` and more than a bare stub (e.g. `C#C*`), else None."""
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return None
    dummies = [a for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    return mol if len(dummies) == 1 and mol.GetNumAtoms() > 2 else None


def join(a, b) -> str | None:
    """Bond two fragments at their `*` atoms with RDKit's molzip and return canonical SMILES."""
    a, b = Chem.RWMol(a), Chem.RWMol(b)
    for mol in (a, b):
        for atom in mol.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetAtomMapNum(1)
    try:
        return canon(Chem.MolToSmiles(Chem.molzip(a, b)))
    except Exception:
        return None


def main() -> None:
    truth: dict[str, dict[str, str]] = {p: {} for p in PAPERS}
    with open(GT, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            truth[row["paperID"]][canon(row["canonical_SMILES"])] = row["name of molecule"]
    with open(RUN, newline="", encoding="utf-8") as f:
        readings = list(csv.DictReader(f))

    lines = ["paper | readings | read directly | one-attachment fragments | same-page joins | new answer-key molecules"]
    examples = []
    totals = [0, 0, 0, 0, 0]
    for paper in PAPERS:
        rows = [r for r in readings if r["paper_id"] == paper]
        direct = {canon(r["smiles"]) for r in rows} & set(truth[paper])
        frags = [(r, m) for r in rows if (m := one_attachment(r["smiles"])) is not None]
        joins, new = 0, {}
        for (ra, ma), (rb, mb) in itertools.combinations(frags, 2):
            if ra["page"] != rb["page"]:
                continue
            smiles = join(ma, mb)
            if smiles is None:
                continue
            joins += 1
            if smiles in truth[paper] and smiles not in direct:
                new.setdefault(smiles, (ra, rb))
        for smiles, (ra, rb) in new.items():
            examples.append(f"paper {paper}, compound {truth[paper][smiles]}: "
                            f"{ra['box_id']} {ra['smiles']}  +  {rb['box_id']} {rb['smiles']}  ->  {smiles}")
        counts = [len(rows), len(direct), len(frags), joins, len(new)]
        totals = [t + c for t, c in zip(totals, counts)]
        lines.append(" | ".join([paper, *map(str, counts)]))
    lines.append(" | ".join(["all", *map(str, totals)]))
    lines += ["", "Recovered molecules (first pairing found):", *examples]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
