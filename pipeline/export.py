"""Export: choose which results of a run become final predictions, and say why the rest did not.

Reads each paper's `regions.csv`, `readings.csv`, `links.jsonl` and
`assemblies.jsonl`, and writes three files at the run root (pipeline/INTERFACES.md):

- `predictions.csv`: one row per exported molecule, in the format
  `benchmarks/score.py` already scores.
- `provenance.jsonl`: for each prediction, every box, table cell and text block
  that contributed to it.
- `export_rejections.jsonl`: readings that were not exported because they do not
  parse or still contain `*`.

A molecule is exported in two cases: a drawing whose selected reading is a
complete, valid molecule, and a table row that assembly completed. Fragments,
scaffolds, abstentions and gated-out regions produce no prediction; they are
counted in `run.json` so lost recall stays visible. The answer key is never
read here.

    python -m pipeline.export data/pipeline_runs/<run_id>
    python benchmarks/score.py data/pipeline_runs/<run_id>     # scoring, unchanged

AI disclosure: Claude Code wrote this file at Will's request, for his review,
and on Nov 17 split export_drawings and export_assemblies into the helpers below.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from rdkit import Chem

from pipeline.stage_io import (DEFAULT_READERS, PREDICTION_COLUMNS, REJECTION_FIELDS,
                               attachment_points, mark_task, paper_dirs, parse_smiles, read_csv, read_jsonl,
                               readings_by_box, select_reading, update_stage, write_csv, write_jsonl)

DEFAULT_GATES = ("molecule",)


# Row builders. Key order matters: it is the column and field order of the output files.

def _location(region: dict) -> dict:
    return {key: region[key] for key in ("page", "x0", "y0", "x1", "y1")}


def _prediction_row(paper_id: str, mol: Chem.Mol, region: dict, label: str, source: str,
                    confidence, box_id: str, method: str, evidence_id: str) -> dict:
    """One `predictions.csv` row, placed at `region` on the page. The ID is added later by export_run."""
    return {"paper_id": paper_id, "smiles": Chem.MolToSmiles(mol), **_location(region),
            "label": label, "source": source, "confidence": confidence, "box_id": box_id,
            "method": method, "evidence_id": evidence_id}


def _provenance_row(paper_id: str, evidence_id: str, method: str, box_ids: list, cell_ids: list,
                    text_block_ids: list, table_id: str | None = None, row_id: str | None = None) -> dict:
    """One `provenance.jsonl` record: every box, cell and text block behind a prediction."""
    return {"paper_id": paper_id, "evidence_id": evidence_id, "method": method, "box_ids": box_ids,
            "cell_ids": cell_ids, "text_block_ids": text_block_ids, "table_id": table_id, "row_id": row_id}


def _rejection(paper_id: str, evidence_id: str, reason: str, raw: str) -> dict:
    """One `export_rejections.jsonl` record."""
    return {"paper_id": paper_id, "evidence_id": evidence_id, "reason": reason, "raw": raw}


def _molecule_problem(mol: Chem.Mol | None) -> str | None:
    """Why a parsed reading is not a complete molecule (`parse_failure`, `unresolved_wildcard`), or None."""
    if mol is None:
        return "parse_failure"
    if attachment_points(mol):
        return "unresolved_wildcard"
    return None


# Drawings

def _table_cell_boxes(paper_dir: Path) -> set[str]:
    """Boxes drawn inside a table cell. Each is a piece of a row, never a molecule of its own."""
    return {cell["box_id"] for table in read_jsonl(paper_dir / "tables.jsonl")
            for row in table.get("rows") or [] for cell in row["cells"] if cell.get("box_id")}


def _drawing_labels(paper_dir: Path) -> dict[str, dict]:
    """The ok label link for each drawing (`12a`), from label linking. Row links are left out."""
    return {link["box_id"]: link for link in read_jsonl(paper_dir / "links.jsonl")
            if link["status"] == "ok" and link.get("label") and not link.get("row_id")}


def _exportable_reading(region: dict, readings: dict[str, list[dict]], readers: tuple[str, ...],
                        gates: tuple[str, ...], counts: Counter) -> dict | None:
    """The region's selected reading if it passed the gate and the reader gave an answer; else count why not."""
    if region["gate"] not in gates:
        counts[f"gate_{region['gate']}"] += 1
        return None
    reading = select_reading(readings.get(region["box_id"], []), readers)
    if reading is None or reading["status"] != "ok":
        counts["reading_abstained" if reading else "no_reading"] += 1
        return None
    return reading


def export_drawings(paper_dir: Path, readers: tuple[str, ...], gates: tuple[str, ...],
                    counts: Counter) -> tuple[list[dict], list[dict], list[dict]]:
    """Turn one paper's complete drawings into prediction, provenance and rejection rows.

    A drawing is exported when it passed the gate, its selected reading parses,
    has no `*` left, and the drawing is not inside a table cell.
    """
    readings = readings_by_box(paper_dir)
    cell_boxes = _table_cell_boxes(paper_dir)
    labels = _drawing_labels(paper_dir)
    predictions, provenance, rejections = [], [], []
    for region in read_csv(paper_dir / "regions.csv"):
        reading = _exportable_reading(region, readings, readers, gates, counts)
        if reading is None:
            continue
        box_id, paper_id = region["box_id"], region["paper_id"]
        evidence_id = f"{box_id}:{reading['reader']}"
        mol = parse_smiles(reading["smiles"])
        reason = _molecule_problem(mol) or ("table_cell_drawing" if box_id in cell_boxes else None)
        if reason:
            counts[reason] += 1
            rejections.append(_rejection(paper_id, evidence_id, reason, reading["smiles"]))
            continue
        link = labels.get(box_id) or {}
        predictions.append(_prediction_row(paper_id, mol, region, link.get("label", ""), "drawing",
                                           reading.get("confidence") or "", box_id, "reading", evidence_id))
        provenance.append(_provenance_row(paper_id, evidence_id, "reading", [box_id], [],
                                          link.get("evidence_block_ids") or []))
        counts["drawing_exported"] += 1
    return predictions, provenance, rejections


# Assemblies

def export_assemblies(paper_dir: Path, counts: Counter) -> tuple[list[dict], list[dict], list[dict]]:
    """Turn one paper's completed assemblies into prediction and provenance rows.

    The prediction sits at the scaffold's position on the page; substituent
    boxes on other pages are kept in provenance.
    """
    regions = {row["box_id"]: row for row in read_csv(paper_dir / "regions.csv")}
    predictions, provenance, rejections = [], [], []
    for assembly in read_jsonl(paper_dir / "assemblies.jsonl"):
        if assembly["status"] != "ok":
            counts[f"assembly_{assembly['status']}"] += 1
            continue
        paper_id, evidence_id = assembly["paper_id"], assembly["assembly_id"]
        mol = parse_smiles(assembly["smiles"])
        reason = _molecule_problem(mol)
        if reason:
            counts[reason] += 1
            rejections.append(_rejection(paper_id, evidence_id, reason, assembly["smiles"]))
            continue
        scaffold_box = assembly["scaffold_box_id"]
        predictions.append(_prediction_row(paper_id, mol, regions[scaffold_box], assembly.get("label") or "",
                                           "unknown", "", scaffold_box, assembly["method"], evidence_id))
        provenance.append(_provenance_row(
            paper_id, evidence_id, assembly["method"], assembly["source_box_ids"],
            [s["cell_id"] for s in assembly.get("substituents") or []], assembly["evidence_block_ids"],
            assembly["table_id"], assembly["row_id"]))
        counts["assembly_exported"] += 1
    return predictions, provenance, rejections


def export_run(run_dir: Path, readers: tuple[str, ...] = DEFAULT_READERS,
               gates: tuple[str, ...] = DEFAULT_GATES) -> dict:
    """Write the run's predictions, provenance and rejections, and record counts in run.json."""
    counts: Counter = Counter()
    predictions, provenance, rejections = [], [], []
    for paper_dir in paper_dirs(run_dir):
        for rows in (export_drawings(paper_dir, readers, gates, counts),
                     export_assemblies(paper_dir, counts)):
            predictions += rows[0]
            provenance += rows[1]
            rejections += rows[2]
    # Prediction IDs are assigned last so they are unique across the whole run.
    for number, (prediction, trace) in enumerate(zip(predictions, provenance), start=1):
        prediction["prediction_id"] = trace["prediction_id"] = f"{prediction['paper_id']}-pred{number}"
    write_csv(run_dir / "predictions.csv", PREDICTION_COLUMNS, predictions)
    write_jsonl(run_dir / "provenance.jsonl", provenance)
    write_jsonl(run_dir / "export_rejections.jsonl",
                [{field: row[field] for field in REJECTION_FIELDS} for row in rejections])
    info = {"status": "complete", "predictions": len(predictions), "rejections": len(rejections),
            "counts": dict(sorted(counts.items())), "readers": list(readers), "gates": list(gates)}
    update_stage(run_dir, "export", info)
    mark_task(run_dir, "e2e", unless=("smoke",))
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("run_dir", type=Path, help="a folder under data/pipeline_runs/")
    parser.add_argument("--readers", nargs="+", default=list(DEFAULT_READERS),
                        help="reader preference order for choosing one reading per box")
    parser.add_argument("--gates", nargs="+", default=list(DEFAULT_GATES),
                        help="gate values whose regions may be exported (add 'uncertain' for an ablation)")
    args = parser.parse_args()
    info = export_run(args.run_dir, tuple(args.readers), tuple(args.gates))
    print(f"{info['predictions']} predictions, {info['rejections']} rejections: {info['counts']}")


if __name__ == "__main__":
    main()
