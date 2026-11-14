"""Stand-in reading stage: run MolGlyph and MolScribe on a run's gated crops.

The pipeline has no reading module yet (Bijay owns readers and the consensus
rule). This fills the gap so assembly, export and scoring can run on real
readings after the front end. For every region with `gate=molecule` and a crop,
each reader writes one row to `papers/<paper_id>/readings.csv` (contract 0.1),
including abstentions. It writes no `consensus` row, so `select_reading` falls
back to MolGlyph, then MolScribe. It also writes an empty `links.jsonl` where
label linking has not run, which assembly treats as "no links" and falls back to
each table's `scaffold_box_id`.

Both readers run on a laptop CPU (about 50 s for paper 19's 54 crops on an M1 Pro).

    python -m pipeline.read_crops data/pipeline_runs/<run_id>

Replace with the real reading stage when it lands.

AI disclosure: Claude Code wrote this file at Will's request, for his review.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from readers import load_reader  # noqa: E402  (benchmarks/readers.py, the Phase 1 reader wrappers)

from pipeline.smoke import READING_COLUMNS  # noqa: E402
from pipeline.stage_io import paper_dirs, read_csv, update_stage, write_csv  # noqa: E402

READERS = ("molglyph", "molscribe")


def read_paper(run_dir: Path, paper_dir: Path, readers: list) -> int:
    """Write one paper's readings.csv; returns the number of crops read."""
    regions = [r for r in read_csv(paper_dir / "regions.csv") if r["gate"] == "molecule" and r["crop_path"]]
    crops = [np.array(Image.open(run_dir / r["crop_path"]).convert("RGB")) for r in regions]
    rows = []
    for reader in readers:
        predictions = reader.predict(crops)
        if len(predictions) != len(regions):  # the contract forbids silently dropped records
            raise RuntimeError(f"{reader.name} returned {len(predictions)} results for {len(regions)} crops")
        for region, prediction in zip(regions, predictions):
            smiles = prediction.get("smiles") or ""
            ok = bool(smiles) and smiles != "<invalid>"
            confidence = prediction.get("confidence")
            rows.append({"paper_id": region["paper_id"], "box_id": region["box_id"], "reader": reader.name,
                         "smiles": smiles if ok else "", "confidence": "" if confidence is None else confidence,
                         "raw": prediction.get("raw") or "", "status": "ok" if ok else "abstain",
                         "reason": "" if ok else "reader returned no valid SMILES"})
    write_csv(paper_dir / "readings.csv", READING_COLUMNS, rows)
    if not (paper_dir / "links.jsonl").exists():
        (paper_dir / "links.jsonl").write_text("", encoding="utf-8")
    return len(regions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("run_dir", type=Path, help="a front-end run folder under data/pipeline_runs/")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    readers = [load_reader(name, device=args.device) for name in READERS]
    total = 0
    for paper_dir in paper_dirs(args.run_dir):
        count = read_paper(args.run_dir, paper_dir, readers)
        total += count
        print(f"paper {paper_dir.name}: {count} crops read")
    update_stage(args.run_dir, "read", {
        "status": "complete", "crops": total, "readers": list(READERS), "device": args.device,
        "versions": {key: value for reader in readers for key, value in reader.versions.items()},
        "note": "stand-in reading stage (pipeline/read_crops.py): no consensus row, empty links.jsonl"})


if __name__ == "__main__":
    main()
