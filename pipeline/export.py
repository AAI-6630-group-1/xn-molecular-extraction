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

AI disclosure: Claude Code wrote this file at Will's request, for his review.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from rdkit import Chem

from pipeline.stage_io import (DEFAULT_READERS, PREDICTION_COLUMNS, REJECTION_FIELDS,
                               attachment_points, paper_dirs, parse_smiles, read_csv, read_jsonl,
                               readings_by_box, select_reading, update_stage, write_csv, write_jsonl)

DEFAULT_GATES = ("molecule",)


def _location(region: dict) -> dict:
    return {key: region[key] for key in ("page", "x0", "y0", "x1", "y1")}


def export_drawings(paper_dir: Path, readers: tuple[str, ...], gates: tuple[str, ...],
                    counts: Counter) -> tuple[list[dict], list[dict], list[dict]]:
    """Turn one paper's complete drawings into prediction, provenance and rejection rows."""
    regions = read_csv(paper_dir / "regions.csv")
    readings = readings_by_box(paper_dir)
    # A drawing inside a table cell is a piece of a row, never a molecule of its own.
    cell_boxes = {cell["box_id"] for table in read_jsonl(paper_dir / "tables.jsonl")
                  for row in table.get("rows") or [] for cell in row["cells"] if cell.get("box_id")}
    labels = {link["box_id"]: link for link in read_jsonl(paper_dir / "links.jsonl")
              if link["status"] == "ok" and link.get("label") and not link.get("row_id")}
    predictions, provenance, rejections = [], [], []
    for region in regions:
        box_id = region["box_id"]
        if region["gate"] not in gates:
            counts[f"gate_{region['gate']}"] += 1
            continue
        reading = select_reading(readings.get(box_id, []), readers)
        if reading is None or reading["status"] != "ok":
            counts["reading_abstained" if reading else "no_reading"] += 1
            continue
        evidence_id = f"{box_id}:{reading['reader']}"
        mol = parse_smiles(reading["smiles"])
        if mol is None:
            reason = "parse_failure"
        elif attachment_points(mol):
            reason = "unresolved_wildcard"
        elif box_id in cell_boxes:
            reason = "table_cell_drawing"
        else:
            reason = None
        if reason:
            counts[reason] += 1
            rejections.append({"paper_id": region["paper_id"], "evidence_id": evidence_id,
                               "reason": reason, "raw": reading["smiles"]})
            continue
        link = labels.get(box_id)
        predictions.append({
            "paper_id": region["paper_id"], "smiles": Chem.MolToSmiles(mol), **_location(region),
            "label": link["label"] if link else "", "source": "drawing",
            "confidence": reading.get("confidence") or "", "box_id": box_id,
            "method": "reading", "evidence_id": evidence_id,
        })
        provenance.append({"paper_id": region["paper_id"], "evidence_id": evidence_id,
                           "method": "reading", "box_ids": [box_id], "cell_ids": [],
                           "text_block_ids": (link or {}).get("evidence_block_ids") or [],
                           "table_id": None, "row_id": None})
        counts["drawing_exported"] += 1
    return predictions, provenance, rejections


def export_assemblies(paper_dir: Path, counts: Counter) -> tuple[list[dict], list[dict], list[dict]]:
    """Turn one paper's completed assemblies into prediction and provenance rows."""
    regions = {row["box_id"]: row for row in read_csv(paper_dir / "regions.csv")}
    predictions, provenance, rejections = [], [], []
    for assembly in read_jsonl(paper_dir / "assemblies.jsonl"):
        if assembly["status"] != "ok":
            counts[f"assembly_{assembly['status']}"] += 1
            continue
        mol = parse_smiles(assembly["smiles"])
        if mol is None or attachment_points(mol):
            reason = "parse_failure" if mol is None else "unresolved_wildcard"
            counts[reason] += 1
            rejections.append({"paper_id": assembly["paper_id"], "evidence_id": assembly["assembly_id"],
                               "reason": reason, "raw": assembly["smiles"]})
            continue
        # The CSV row sits at the scaffold; pieces on other pages stay in provenance.
        scaffold = regions[assembly["scaffold_box_id"]]
        predictions.append({
            "paper_id": assembly["paper_id"], "smiles": Chem.MolToSmiles(mol), **_location(scaffold),
            "label": assembly.get("label") or "", "source": "unknown", "confidence": "",
            "box_id": assembly["scaffold_box_id"], "method": assembly["method"],
            "evidence_id": assembly["assembly_id"],
        })
        provenance.append({"paper_id": assembly["paper_id"], "evidence_id": assembly["assembly_id"],
                           "method": assembly["method"], "box_ids": assembly["source_box_ids"],
                           "cell_ids": [s["cell_id"] for s in assembly.get("substituents") or []],
                           "text_block_ids": assembly["evidence_block_ids"],
                           "table_id": assembly["table_id"], "row_id": assembly["row_id"]})
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
