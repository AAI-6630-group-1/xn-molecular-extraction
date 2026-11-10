"""Turn a committed Phase 1 benchmark run into a pipeline run folder.

The Phase 1 runs (benchmarks/results/<handle>/<run_id>/predictions.csv) already
hold MolDetV2 boxes and one reader's SMILES for the six internal papers. This
script rewrites one of them as `regions.csv` and `readings.csv` in the Phase 2
layout, with empty `tables.jsonl` and `links.jsonl`, so assembly and export can
run on real readings before the front end and linking modules exist. No model
runs; it takes a second on a laptop CPU.

Phase 1 had no molecule gate, so every box gets `gate=molecule` and
`role=unknown`. The table and link stages are recorded as stubs in run.json.

    python -m pipeline.phase1_run benchmarks/results/willdaly/<run_id> --out data/pipeline_runs/<new_id>
    python -m pipeline.assembly data/pipeline_runs/<new_id>
    python -m pipeline.export data/pipeline_runs/<new_id>
    python benchmarks/score.py data/pipeline_runs/<new_id>

AI disclosure: Claude Code wrote this file at Will's request, for his review.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path

from pipeline.smoke import READING_COLUMNS, REGION_COLUMNS, git_revision
from pipeline.stage_io import read_csv, write_csv, write_jsonl


def convert(source: Path, out: Path) -> dict:
    """Write the pipeline run folder and return its run.json contents."""
    source_meta = json.loads((source / "run.json").read_text(encoding="utf-8"))
    reader = source_meta["settings"]["reader"]
    rows = read_csv(source / "predictions.csv")
    out.mkdir(parents=True, exist_ok=False)  # never replace an earlier run
    papers = list(dict.fromkeys(row["paper_id"] for row in rows))
    for paper in papers:
        paper_dir = out / "papers" / paper
        paper_dir.mkdir(parents=True)
        boxes = [row for row in rows if row["paper_id"] == paper]
        write_csv(paper_dir / "regions.csv", REGION_COLUMNS, [
            {"paper_id": paper, "page": b["page"], "box_id": b["box_id"],
             "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"], "crop_path": "",
             "role": "unknown", "gate": "molecule", "confidence": b.get("det_confidence", ""),
             "reason": "Phase 1 run: no gate applied"} for b in boxes])
        write_csv(paper_dir / "readings.csv", READING_COLUMNS, [
            {"paper_id": paper, "box_id": b["box_id"], "reader": reader, "smiles": b["smiles"],
             "confidence": b.get("confidence", ""), "raw": "",
             "status": "ok" if b["smiles"] else "abstain",
             "reason": "" if b["smiles"] else "no valid SMILES"} for b in boxes])
        write_jsonl(paper_dir / "tables.jsonl", [])
        write_jsonl(paper_dir / "links.jsonl", [])
    stub = {"status": "stub", "records": 0, "reason": "module not built yet"}
    meta = {
        "schema_version": "0.1", "task": "e2e", "dataset": source_meta["dataset"],
        "handle": source_meta.get("handle"), "tool": f"phase2-export-of-{source_meta['tool']}",
        "paper_ids": papers, "source_run": source.name, "git_commit": git_revision(),
        "versions": {**source_meta.get("versions", {}),
                     "rdkit": importlib.metadata.version("rdkit")},
        "hardware": source_meta.get("hardware"),
        "notes": "Boxes and readings copied from a Phase 1 run; no gate, tables or links.",
        "stages": {
            "detect_gate": {"status": "complete", "records": len(rows),
                            "reason": "Phase 1 MolDetV2 boxes, every box passed as molecule"},
            "tables": stub, "link": stub,
            "read_consensus": {"status": "complete", "records": len(rows), "reader": reader},
        },
    }
    (out / "run.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", type=Path, help="a Phase 1 run folder with predictions.csv and run.json")
    parser.add_argument("--out", type=Path, required=True, help="new pipeline run folder")
    args = parser.parse_args()
    meta = convert(args.source, args.out)
    print(f"Wrote {meta['stages']['detect_gate']['records']} boxes for papers "
          f"{', '.join(meta['paper_ids'])} to {args.out}")


if __name__ == "__main__":
    main()
