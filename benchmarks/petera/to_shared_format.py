#!/usr/bin/env python3
"""Convert Peter's BioVista runs into the team's shared results format (#14, #22).

    uv run python benchmarks/petera/to_shared_format.py
    uv run python benchmarks/score.py --all && uv run python benchmarks/aggregate.py

Peter's benchmark (benchmark_1/, results in benchmark_1_results/) scored MolGlyph and MolNexTR
with its own scorer. This writes its BioVista rows as predictions.csv + run.json under
benchmarks/results/PeterAdr14/, so score.py rescores them against the same ground truth as
everyone else's runs and aggregate.py puts them in the team table.

Only BioVista converts: it is the one dataset of his that score.py knows. CLEF, UOB, USPTO and
JPO stay in his comparison.csv, which aggregate.py reads as a separate table.

His BioVista run is a seeded 1,000-crop sample of all 8,861 crops, so run.json sets
"crop_sample": true and score.py scores only those crops. The SMILES are the tools' raw
output (pred_smiles), not his canonicalized column, so our canonicalization applies.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "benchmark_1_results"
RESULTS = HERE.parent / "results" / "PeterAdr14"

# His tool name -> (our tool name, description). MolGlyph gets its own name so it doesn't
# replace Will's full-set MolGlyph run in the systems table.
TOOLS = {
    "biominer_molglyph": ("molglyph-sample", "MolGlyph (BioMiner's recognizer, postprocessing on)"),
    "molnextr": ("molnextr", "MolNexTR"),
}


def crop_id(sample_id: str) -> str:
    """ocsr/data/51_6rrm_image_molminer_bbox_3-6 -> 51_6rrm_image_molminer_bbox_3-6"""
    return sample_id.rsplit("/", 1)[-1]


def main() -> None:
    meta = json.loads((SOURCE / "run_metadata.json").read_text())
    with open(SOURCE / "predictions.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["dataset"] == "biovista_ocsr"]
    day = meta["started_at"][:10]
    env = meta["environment"]

    for theirs, (tool, label) in TOOLS.items():
        mine = [r for r in rows if r["tool"] == theirs]
        run_dir = RESULTS / f"{day}_{tool}_biovista"
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "predictions.csv", "w", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["paper_id", "smiles", "confidence", "raw"])
            for r in mine:
                writer.writerow([crop_id(r["sample_id"]), r["pred_smiles"], r["confidence"], r["pred_smiles"]])
        resources = meta["tool_resources"].get(theirs, {})
        versions = {"python": env["python"], "rdkit": env["packages"].get("rdkit"), "torch": env["packages"].get("torch")}
        if theirs == "molnextr":
            versions.update(python=resources.get("worker_python"), torch=resources.get("worker_torch"),
                            molnextr_commit=resources.get("molnextr_commit"))
        else:
            versions["biominer_commit"] = resources.get("biominer_commit")
        run = {
            "handle": "PeterAdr14",
            "tool": tool,
            "task": "ocsr",
            "dataset": "biovista",
            "crop_sample": True,
            "pipeline": f"{label} on each BioVista OCSR crop, a seeded sample of {len(mine):,} of the 8,861 crops",
            "settings": {"n_crops": len(mine), "seed": meta["config"]["run"]["seed"],
                         "batch_size": meta["config"]["run"]["batch_size"]},
            "versions": versions,
            "command": "python -m ocsr_bench run (benchmarks/petera/benchmark_1, configs/default.yaml)",
            "git_commit": "ee85f7b",
            "hardware": f"{env['platform']}, {env['gpu']}",
            "runtime_s": None,
            "api_cost_usd": None,
            "notes": ("Converted from benchmarks/petera/benchmark_1_results/predictions.csv by "
                      "benchmarks/petera/to_shared_format.py. git_commit is the commit that added the code and results."),
        }
        (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
        print(f"wrote {run_dir} ({len(mine)} crops)")


if __name__ == "__main__":
    main()
