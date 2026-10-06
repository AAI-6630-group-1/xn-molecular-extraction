#!/usr/bin/env python3
"""Recognition (OCSR) on BioVista: one SMILES per molecule crop, with MolScribe or MolGlyph.

BioVista is the benchmark released with BioMiner (Yan et al., 2026). Its OCSR
task gives 8,861 molecule crops from 335 papers with one ground-truth SMILES
each, and 45% of them are Markush scaffolds with R-group placeholders. Running
both readers on it puts MolScribe (the sponsor paper's recognizer) side by side
with MolGlyph (BioMiner's), on the data BioMiner was evaluated on.

    uv run python benchmarks/willdaly/run_biovista.py --reader molscribe
    uv run python benchmarks/willdaly/run_biovista.py --reader molglyph
    uv run python benchmarks/willdaly/run_biovista.py --reader molglyph --limit 50   # quick check
    uv run python benchmarks/score.py benchmarks/results/willdaly/<run_id>

Needs the OCSR set in data/biovista/ (benchmarks/willdaly/download_data.py
fetches it). Writes predictions.csv as it goes, so an interrupted run picks up
where it stopped with --resume.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "data" / "biovista" / "ocsr" / "data"
sys.path.insert(0, str(HERE))
from readers import READERS, load_reader  # noqa: E402
from run_track3 import git_commit, hardware, versions  # noqa: E402

COLUMNS = ["paper_id", "smiles", "confidence", "raw"]
CHUNK = 64  # crops read between writes to predictions.csv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reader", choices=READERS, default="molscribe")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--limit", type=int, help="read only the first N crops (for a quick check)")
    ap.add_argument("--resume", action="store_true", help="keep the rows already in predictions.csv")
    ap.add_argument("--run-id", help="default: <today>_<reader>_biovista")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    crops = sorted(DATA.glob("*.png"))
    if not crops:
        sys.exit(f"no crops in {DATA}; run benchmarks/willdaly/download_data.py --biovista")
    crops = crops[:args.limit] if args.limit else crops

    run_id = args.run_id or f"{date.today().isoformat()}_{args.reader}_biovista"
    run_dir = REPO / "benchmarks" / "results" / "willdaly" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    pred_path = run_dir / "predictions.csv"

    done: set[str] = set()
    if args.resume and pred_path.exists():
        with open(pred_path, newline="", encoding="utf-8") as f:
            done = {row["paper_id"] for row in csv.DictReader(f)}
    todo = [p for p in crops if p.stem not in done]
    print(f"{len(crops)} crops, {len(done)} already read, {len(todo)} to go", flush=True)

    reader = load_reader(args.reader, args.device)
    t0 = time.perf_counter()
    with open(pred_path, "a" if done else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if not done:
            writer.writeheader()
        for start in range(0, len(todo), CHUNK):
            chunk = todo[start:start + CHUNK]
            images = [np.asarray(Image.open(p).convert("RGB")) for p in chunk]
            for path, pred in zip(chunk, reader.predict(images)):
                writer.writerow({"paper_id": path.stem, "smiles": pred["smiles"],
                                 "confidence": round(pred["confidence"], 4), "raw": pred["raw"]})
            f.flush()
            n = start + len(chunk)
            rate = (time.perf_counter() - t0) / n
            print(f"  {n}/{len(todo)} crops, {rate:.2f} s/crop, about {rate * (len(todo) - n) / 60:.0f} min left",
                  flush=True)
    runtime = time.perf_counter() - t0

    previous = json.loads((run_dir / "run.json").read_text()) if done and (run_dir / "run.json").exists() else {}
    run = {
        "handle": "willdaly", "tool": args.reader, "track": 3, "task": "ocsr", "dataset": "biovista",
        "pipeline": f"{args.reader} on each BioVista OCSR crop as distributed (no extra margin or resizing)",
        "settings": {"n_crops": len(crops), "device": args.device},
        "versions": {**versions(), **reader.versions},
        "command": "uv run python " + " ".join(shlex.quote(a) for a in [
            str(Path(sys.argv[0]).resolve().relative_to(REPO)), *sys.argv[1:]]),
        "git_commit": git_commit(), "hardware": f"{hardware()}, {args.device}",
        # Resumed runs add this session's time to the earlier sessions'.
        "runtime_s": {"all": round(runtime + previous.get("runtime_s", {}).get("all", 0.0), 1)},
        "api_cost_usd": None, "notes": args.notes,
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    print(f"wrote {run_dir.relative_to(REPO)} ({len(crops)} crops, {runtime / 60:.1f} min this session)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
