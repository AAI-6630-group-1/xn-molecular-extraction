"""Reading and consensus stage (Bijay's 2.3 module).

Reads every candidate crop of a front-end run with two OCSR readers, MolGlyph
(primary) and MolScribe (second), and writes `papers/<paper_id>/readings.csv`
(contract 0.1, pipeline/INTERFACES.md):

* one row per `(box_id, reader)`, abstentions and errors included, so assembly
  and export can tell "no answer" from "failed";
* one extra `reader=consensus` row per box, which `select_reading` prefers.

Consensus rule (version 1):

1. Both readers give a valid SMILES and the canonical forms match: agreement,
   the strongest evidence this stage can give. The MolGlyph row is kept.
2. Both are valid but differ: MolGlyph is the primary reader, so its row is kept
   and the reason says "disagree". Reader confidences are not calibrated against
   each other and are never used to break ties.
3. Only one reader is valid: that reader's row is kept and the reason says which.
4. Neither is valid: the consensus row abstains (no SMILES), or is an error if a
   reader failed on that crop.

A consensus row copies the chosen reader's `smiles`, `confidence` and `raw`
unchanged. MolGlyph's `raw` records the drawn label of each `*` (`<a>5:A</a>`),
which assembly needs to match table columns to scaffold positions, so whenever
MolGlyph is valid the consensus row is MolGlyph's row.

The stage records `status`, counts and agreement numbers under `stages.read` in
run.json. A reader that raises or returns the wrong number of results gets
`status=error` rows and the stage is marked `error`; it never becomes an empty
success.

    python -m pipeline.reading data/pipeline_runs/<run_id>

Models load through benchmarks/readers.py (`load_reader`) and run on a CPU;
`--device cuda` only speeds them up.

AI disclosure: Took Claude Code help.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from PIL import Image
from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.smoke import READING_COLUMNS  # noqa: E402
from pipeline.stage_io import paper_dirs, parse_smiles, read_csv, update_stage, write_csv  # noqa: E402

READERS = ("molglyph", "molscribe")  # primary first
GATES = ("molecule", "uncertain")  # INTERFACES.md: the reader gets accepted and uncertain crops
CONSENSUS = "consensus"
INVALID = "<invalid>"  # what MolScribe writes when it cannot build a molecule


def canonical(smiles: str | None) -> str | None:
    """RDKit's default canonical SMILES, or None when the text is empty or does not parse."""
    mol = parse_smiles(smiles)
    return Chem.MolToSmiles(mol) if mol is not None else None


def reader_row(region: dict, reader: str, prediction: dict) -> dict:
    """One readings.csv row from one reader's answer for one crop (`ok` or `abstain`)."""
    smiles = prediction.get("smiles") or ""
    ok = bool(smiles) and smiles != INVALID
    confidence = prediction.get("confidence")
    return {"paper_id": region["paper_id"], "box_id": region["box_id"], "reader": reader,
            "smiles": smiles if ok else "", "confidence": "" if confidence is None else confidence,
            "raw": prediction.get("raw") or "", "status": "ok" if ok else "abstain",
            "reason": "" if ok else "reader returned no valid SMILES"}


def error_row(region: dict, reader: str, reason: str) -> dict:
    """A row for a crop the reader could not process."""
    return {"paper_id": region["paper_id"], "box_id": region["box_id"], "reader": reader,
            "smiles": "", "confidence": "", "raw": "", "status": "error", "reason": reason}


def usable(row: dict | None) -> bool:
    """True when the row is `ok` and its SMILES parses."""
    return bool(row) and row["status"] == "ok" and canonical(row["smiles"]) is not None


def consensus_row(box_rows: dict[str, dict], readers: Sequence[str] = READERS) -> dict:
    """The consensus row for one box, from its rows keyed by reader name.

    `readers` lists the primary reader first. See the module docstring for the rule.
    """
    first = next(iter(box_rows.values()))
    base = {"paper_id": first["paper_id"], "box_id": first["box_id"], "reader": CONSENSUS}
    valid = [name for name in readers if usable(box_rows.get(name))]
    if valid:
        chosen = box_rows[valid[0]]
        if len(valid) == len(readers):
            same = len({canonical(box_rows[name]["smiles"]) for name in valid}) == 1
            reason = "agree" if same else f"disagree: {valid[0]} kept"
        else:
            missing = ", ".join(f"{n} {'unparsable' if box_rows[n]['status'] == 'ok' else box_rows[n]['status']}"
                                for n in readers if n not in valid and n in box_rows)
            reason = f"{valid[0]} only: {missing}"
        return {**base, "smiles": chosen["smiles"], "confidence": chosen["confidence"], "raw": chosen["raw"],
                "status": "ok", "reason": reason}
    failed = [n for n in readers if n in box_rows and box_rows[n]["status"] == "error"]
    status, reason = ("error", f"reader failed: {', '.join(failed)}") if failed else \
        ("abstain", "no reader gave a valid SMILES")
    return {**base, "smiles": "", "confidence": "", "raw": "", "status": status, "reason": reason}


def build_consensus(rows: list[dict], readers: Sequence[str] = READERS) -> list[dict]:
    """Consensus rows for every box in `rows` (reader rows), in first-seen box order."""
    by_box: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_box.setdefault(row["box_id"], {})[row["reader"]] = row
    return [consensus_row(box_rows, readers) for box_rows in by_box.values()]


def select_regions(paper_dir: Path, gates: Sequence[str] = GATES) -> list[dict]:
    """Regions of one paper that pass the gate and have a crop file to read."""
    return [r for r in read_csv(paper_dir / "regions.csv") if r["gate"] in gates and r["crop_path"]]


def read_crops(run_dir: Path, regions: list[dict], readers: Sequence) -> list[dict]:
    """Run each reader on all regions' crops; returns one row per (region, reader).

    A reader that raises, or returns a different number of results than crops,
    gets an `error` row for every crop (the contract forbids silently dropped
    records); the other readers still run.
    """
    crops = [np.array(Image.open(run_dir / r["crop_path"]).convert("RGB")) for r in regions]
    rows = []
    for reader in readers:
        try:
            predictions = reader.predict(crops) if crops else []
            if len(predictions) != len(regions):
                raise RuntimeError(f"returned {len(predictions)} results for {len(regions)} crops")
        except Exception as exc:  # a failed reader is recorded, not hidden
            rows += [error_row(r, reader.name, f"{type(exc).__name__}: {exc}") for r in regions]
            continue
        rows += [reader_row(r, reader.name, p) for r, p in zip(regions, predictions)]
    return rows


def read_paper(run_dir: Path, paper_dir: Path, readers: Sequence, gates: Sequence[str] = GATES) -> list[dict]:
    """Write one paper's readings.csv (reader rows, then consensus rows) and return all rows."""
    regions = select_regions(paper_dir, gates)
    rows = read_crops(run_dir, regions, readers)
    rows += build_consensus(rows, [r.name for r in readers])
    write_csv(paper_dir / "readings.csv", READING_COLUMNS, rows)
    if not (paper_dir / "links.jsonl").exists():  # label linking has not run: "no links"
        (paper_dir / "links.jsonl").write_text("", encoding="utf-8")
    return rows


def summarize(rows: list[dict]) -> dict:
    """Counts for run.json: rows per reader and status, and how often the readers agreed."""
    counts = Counter(f"{r['reader']}_{r['status']}" for r in rows)
    agreement = Counter(r["reason"].split(":")[0].split(" ")[0] for r in rows
                        if r["reader"] == CONSENSUS and r["status"] == "ok")
    return {**dict(sorted(counts.items())),
            "consensus_agree": agreement["agree"], "consensus_disagree": agreement["disagree"]}


def read_run(run_dir: Path, readers: Sequence, gates: Sequence[str] = GATES,
             versions: dict | None = None, device: str = "cpu") -> dict:
    """Read every paper in a front-end run and record the stage in run.json."""
    all_rows: list[dict] = []
    for paper_dir in paper_dirs(run_dir):
        rows = read_paper(run_dir, paper_dir, readers, gates)
        all_rows += rows
        print(f"paper {paper_dir.name}: {len({r['box_id'] for r in rows})} crops read")
    summary = summarize(all_rows)
    failed = any(r["status"] == "error" for r in all_rows)
    info = {"status": "error" if failed else "complete", "readers": [r.name for r in readers],
            "gates": list(gates), "device": device, "versions": versions or {}, "counts": summary,
            "consensus_rule": "v1: agree -> MolGlyph row; disagree -> MolGlyph kept; one valid reader -> that row"}
    update_stage(run_dir, "read", info)
    return info


def main(argv: Sequence[str] | None = None, loader: Callable | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("run_dir", type=Path, help="a front-end run folder under data/pipeline_runs/")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--gates", nargs="+", default=list(GATES), help="regions with these gate values are read")
    args = parser.parse_args(argv)
    if loader is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
        from readers import load_reader as loader  # noqa: E402  (benchmarks/readers.py)
    readers = [loader(name, device=args.device) for name in READERS]
    versions = {key: value for reader in readers for key, value in reader.versions.items()}
    info = read_run(args.run_dir, readers, tuple(args.gates), versions, args.device)
    print(f"reading {info['status']}: {info['counts']}")
    return 1 if info["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
