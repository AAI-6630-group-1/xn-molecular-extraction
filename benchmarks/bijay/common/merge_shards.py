#!/usr/bin/env python3
"""Join the parts of a sharded run into the predictions.csv and run.json that benchmarks/score.py reads.

    python common/merge_shards.py results/2026-10-18_decimer_biovista

Expects predictions.part0ofN.csv ... predictions.part<N-1>ofN.csv and the matching run.part*.json,
all written by ocsr_run.py. Refuses to merge if a part is missing or a crop appears twice.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

COLUMNS = ["paper_id", "smiles", "confidence", "raw"]


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    run_dir = Path(sys.argv[1])
    parts = sorted(run_dir.glob("predictions.part*of*.csv"))
    if not parts:
        sys.exit(f"no predictions.part*of*.csv in {run_dir}")
    n = int(re.search(r"of(\d+)\.csv$", parts[0].name).group(1))
    missing = {f"predictions.part{i}of{n}.csv" for i in range(n)} - {p.name for p in parts}
    if missing:
        sys.exit("missing parts: " + ", ".join(sorted(missing)))

    rows, seen = [], set()
    for part in parts:
        with open(part, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["paper_id"] in seen:
                    sys.exit(f"crop {row['paper_id']} appears in more than one part")
                seen.add(row["paper_id"])
                rows.append(row)
    rows.sort(key=lambda r: r["paper_id"])
    with open(run_dir / "predictions.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    runs = [json.loads((run_dir / f"run.part{i}of{n}.json").read_text()) for i in range(n)]
    merged = dict(runs[0])
    merged["settings"] = {**runs[0]["settings"], "shard": f"all {n}", "n_crops_written": len(rows)}
    merged["runtime_s"] = {"all": round(sum(r["runtime_s"]["all"] for r in runs), 1)}  # total compute, not wall clock
    merged["runtime_by_shard_s"] = [r["runtime_s"]["all"] for r in runs]
    merged["hardware"] = " | ".join(dict.fromkeys(r["hardware"] for r in runs))
    merged["git_commit"] = ", ".join(dict.fromkeys(r["git_commit"] for r in runs))
    (run_dir / "run.json").write_text(json.dumps(merged, indent=2) + "\n")

    expected = runs[0]["settings"]["n_crops"]
    status = "complete" if len(rows) == expected else f"INCOMPLETE: {len(rows)} of {expected} crops"
    print(f"merged {n} parts into {run_dir / 'predictions.csv'}: {len(rows)} rows ({status})")
    return 0 if len(rows) == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
