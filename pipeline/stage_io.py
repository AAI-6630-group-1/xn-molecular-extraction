"""Read and write the stage files of one pipeline run (pipeline/INTERFACES.md, contract 0.1).

Shared by the assembly and export modules. A missing input file raises
FileNotFoundError: the contract treats a missing file as an error, and only an
empty file as "zero records".

AI disclosure: Claude Code wrote this file at Will's request, for his review.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")  # unreadable SMILES are expected input, not news

ASSEMBLY_FIELDS = (
    "paper_id assembly_id scaffold_box_id table_id row_id label smiles source_box_ids "
    "evidence_block_ids method status reason substituents"
).split()
PREDICTION_COLUMNS = (
    "paper_id smiles page x0 y0 x1 y1 label source confidence box_id "
    "prediction_id method evidence_id"
).split()
REJECTION_FIELDS = "paper_id evidence_id reason raw".split()
# Bijay's consensus row wins when it exists; otherwise the primary reader (MolGlyph).
DEFAULT_READERS = ("consensus", "molglyph", "molscribe")


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def paper_dirs(run_dir: Path) -> list[Path]:
    """The papers/<paper_id>/ folders of a run, in a stable order."""
    papers = run_dir / "papers"
    if not papers.is_dir():
        raise FileNotFoundError(f"{papers} is missing; is {run_dir} a pipeline run folder?")
    return sorted((p for p in papers.iterdir() if p.is_dir()),
                  key=lambda p: (not p.name.isdigit(), int(p.name) if p.name.isdigit() else 0, p.name))


def update_stage(run_dir: Path, stage: str, info: dict) -> None:
    """Record one stage's status and counts in run.json, leaving the rest untouched."""
    path = run_dir / "run.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.setdefault("stages", {})[stage] = info
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def mark_task(run_dir: Path, task: str, unless: tuple[str, ...] = ()) -> None:
    """Set run.json's top-level `task`, keeping the earlier value under `producer_task`.

    The front end labels its run `frontend`, but once export has written
    predictions.csv the run is an end-to-end run, and benchmarks/score.py only
    scores runs labelled `e2e`. Runs already labelled one of `unless` (the
    smoke runner's `smoke`) keep their label.
    """
    path = run_dir / "run.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("task") not in (task, *unless):
        meta.setdefault("producer_task", meta.get("task"))
        meta["task"] = task
        path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


_STAR_LABEL = re.compile(r"<a>(\d+):([^<]+)</a>")


def labelled_scaffold(reading: dict) -> tuple[str, dict[int, str]]:
    """Return a reading's SMILES and the drawn label of each `*`, when the reader kept them.

    MolGlyph's raw output is its SMILES, then `<sep>`, then one `<a>index:label</a>`
    per labelled atom (`<a>5:A</a>`, `<a>3:R[b]</a>`). The indices count atoms in
    that raw SMILES, not in the canonical `smiles` column, so the raw SMILES is
    returned with them. Readers without labels give the `smiles` column and {}.
    """
    raw = reading.get("raw") or ""
    head, _, tail = raw.partition("<sep>")
    labels = {int(index): label.strip() for index, label in _STAR_LABEL.findall(tail)}
    mol = parse_smiles(head) if labels else None
    if mol is None or any(index >= mol.GetNumAtoms() for index in labels):
        return reading["smiles"], {}
    stars = {index: label for index, label in labels.items() if mol.GetAtomWithIdx(index).GetAtomicNum() == 0}
    return (head, stars) if stars else (reading["smiles"], {})


def parse_smiles(smiles: str | None) -> Chem.Mol | None:
    """Parse a SMILES string, returning None for empty or invalid input."""
    if not smiles or not smiles.strip():
        return None
    try:
        return Chem.MolFromSmiles(smiles.strip())
    except Exception:  # RDKit raises on some malformed input instead of returning None
        return None


def attachment_points(mol: Chem.Mol) -> list[Chem.Atom]:
    """The `*` atoms of a molecule: where a substituent still has to go."""
    return [atom for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]


def select_reading(readings: list[dict], readers: tuple[str, ...] = DEFAULT_READERS) -> dict | None:
    """Pick one box's reading: the first reader in `readers` that has a row for it.

    The chosen row is returned even if it is an abstention. If MolGlyph gave no
    answer, we do not quietly fall back to the second reader, because that would
    be a consensus rule, and the consensus rule belongs to the reading module.
    """
    by_reader = {row["reader"]: row for row in readings}
    for reader in readers:
        if reader in by_reader:
            return by_reader[reader]
    return None


def readings_by_box(paper_dir: Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in read_csv(paper_dir / "readings.csv"):
        grouped.setdefault(row["box_id"], []).append(row)
    return grouped
