#!/usr/bin/env python3
"""Compare each sweep setting with the committed baseline run: boxes gained, and molecules kept.

Run sweep.py first. A box counts as the same box at IoU >= 0.5. "Lost" means a
baseline box no box in that setting matches, so molecules_kept shows whether a
setting would drop a molecule the baseline run reads correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "benchmarks"), str(REPO / "benchmarks" / "willdaly")]
from score import parse  # noqa: E402

RESULTS = REPO / "benchmarks" / "results" / "willdaly"
OUT = RESULTS / "2026-11-06_detector-sweep_internal"
RUN = RESULTS / "2026-10-06_moldetv2-molglyph_internal"
SCALE = 300 / 72  # PDF points -> pixels at 300 dpi


def iou(a: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """IoU of box a with each row of boxes."""
    ix = np.clip(np.minimum(a[2], boxes[:, 2]) - np.maximum(a[0], boxes[:, 0]), 0, None)
    iy = np.clip(np.minimum(a[3], boxes[:, 3]) - np.maximum(a[1], boxes[:, 1]), 0, None)
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1])
                    + (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]) - inter + 1e-9)


def main() -> int:
    boxes = pd.read_csv(OUT / "boxes.csv", dtype={"paper_id": str})
    run = pd.read_csv(RUN / "predictions.csv", dtype={"paper_id": str})
    gt = pd.read_csv(RUN / "matches.csv", dtype={"paper_id": str}).query("side == 'gt'")
    truth = {p: {parse(s).key for s in g.smiles} for p, g in gt.groupby("paper_id")}
    run["key"] = [parse(s).key if isinstance(s, str) and s else None for s in run.smiles]
    run["correct"] = [k in truth[p] for p, k in zip(run.paper_id, run.key)]
    all_correct = {(r.paper_id, r.key) for r in run[run.correct].itertuples()}
    coords = ["x0", "y0", "x1", "y1"]
    base = boxes[(boxes.config == "page960") & (boxes.conf >= 0.5)]
    print(f"baseline boxes here {len(base)}, in the committed run {len(run)}")

    rows, extra = [], []
    for config in boxes.config.unique():
        for floor in (0.5, 0.26, 0.1):
            kept_boxes = boxes[(boxes.config == config) & (boxes.conf >= floor)]
            gained = 0
            for (paper, page), group in kept_boxes.groupby(["paper_id", "page"]):
                reference = base[(base.paper_id == paper) & (base.page == page)][coords].values
                for r in group.itertuples():
                    a = np.array([r.x0, r.y0, r.x1, r.y1])
                    if len(reference) and iou(a, reference).max() >= 0.5:
                        continue
                    gained += 1
                    extra.append((config, floor, paper, page, *a, r.conf))
            lost, kept = 0, set()
            for r in run.itertuples():
                candidates = kept_boxes[(kept_boxes.paper_id == r.paper_id) & (kept_boxes.page == r.page)]
                a = np.array([r.x0, r.y0, r.x1, r.y1]) * SCALE
                if len(candidates) and iou(a, candidates[coords].values).max() >= 0.5:
                    if r.correct:
                        kept.add((r.paper_id, r.key))
                else:
                    lost += 1
            rows.append((config, floor, len(kept_boxes), gained, lost, len(kept), len(all_correct - kept)))
    table = pd.DataFrame(rows, columns=["config", "conf", "boxes", "gained", "baseline_lost",
                                        "molecules_kept", "molecules_lost"])
    table.to_csv(OUT / "settings.csv", index=False)
    print(table.to_string(index=False))
    pd.DataFrame(extra, columns="config th paper_id page x0 y0 x1 y1 conf".split()).to_csv(OUT / "extra.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
