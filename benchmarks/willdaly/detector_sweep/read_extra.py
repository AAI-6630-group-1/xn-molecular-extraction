#!/usr/bin/env python3
"""Read every box the sweep gained with MolGlyph and score it against the answer key.

Run compare_boxes.py first. Writes extra_read.csv to the results folder. The
contact sheet shows crops from the papers, so it goes to the gitignored
data/detector_sweep/ folder rather than the results folder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "benchmarks"), str(REPO / "benchmarks" / "willdaly")]
from analyze_track3 import classify_box  # noqa: E402
from readers import load_reader  # noqa: E402
from score import parse  # noqa: E402
from smoke_test_track3 import render  # noqa: E402

RESULTS = REPO / "benchmarks" / "results" / "willdaly"
OUT = RESULTS / "2026-11-06_detector-sweep_internal"
RUN = RESULTS / "2026-10-06_moldetv2-molglyph_internal"
SHEET = REPO / "data" / "detector_sweep" / "extra_sheet.png"
PAD = 10  # px, MolGlyph's margin from run_track3.py


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def unique_boxes(extra: pd.DataFrame) -> list[dict]:
    """Merge the same box found by several settings, remembering which settings found it."""
    reps = []
    for (paper, page), group in extra.groupby(["paper_id", "page"]):
        kept = []
        for r in group.sort_values("conf", ascending=False).itertuples():
            box = (r.x0, r.y0, r.x1, r.y1)
            hit = next((k for k in kept if iou(box, k["box"]) >= 0.5), None)
            if hit is None:
                hit = {"paper": paper, "page": int(page), "box": box, "conf": r.conf, "in": set()}
                kept.append(hit)
            hit["in"].add((r.config, r.th))
        reps += kept
    return reps


def main() -> int:
    gt = pd.read_csv(RUN / "matches.csv", dtype={"paper_id": str}).query("side == 'gt'")
    truth = {p: {parse(s).key for s in g.smiles} for p, g in gt.groupby("paper_id")}
    found = {p: {parse(s).key for s in g[g.status == "TP"].smiles} for p, g in gt.groupby("paper_id")}
    print("baseline found", sum(map(len, found.values())), "of", sum(map(len, truth.values())))
    reps = unique_boxes(pd.read_csv(OUT / "extra.csv", dtype={"paper_id": str}))
    print("unique extra boxes", len(reps))

    reader = load_reader("molglyph", "cpu")
    for paper in sorted({r["paper"] for r in reps}, key=int):
        pages = render(REPO / "data" / "internal" / f"{paper}.pdf", 300)
        here = [r for r in reps if r["paper"] == paper]
        crops = []
        for r in here:
            img = pages[r["page"] - 1]
            h, w, _ = img.shape
            x0, y0, x1, y1 = map(int, r["box"])
            crops.append(img[max(0, y0 - PAD):min(h, y1 + PAD), max(0, x0 - PAD):min(w, x1 + PAD)])
        for r, crop, pred in zip(here, crops, reader.predict(crops)):
            key = parse(pred["smiles"]).key if pred["smiles"] else None
            r.update(smiles=pred["smiles"], rconf=pred["confidence"], crop=crop, key=key,
                     cls=classify_box(pred["smiles"], truth[paper]),
                     new_tp=key in truth[paper] and key not in found[paper])

    print(pd.Series([r["cls"] for r in reps]).value_counts().to_string())
    print("boxes that read as a molecule the baseline missed:", sum(r["new_tp"] for r in reps))
    pd.DataFrame([{k: v for k, v in r.items() if k not in ("crop", "in")} | {"configs": sorted(r["in"])}
                  for r in reps]).to_csv(OUT / "extra_read.csv", index=False)

    reps.sort(key=lambda r: -len(r["in"]))
    size, cols = 190, 8
    sheet = Image.new("RGB", (cols * size, int(np.ceil(len(reps) / cols)) * (size + 22)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, r in enumerate(reps):
        thumb = Image.fromarray(r["crop"])
        thumb.thumbnail((size - 6, size - 6))
        x, y = (i % cols) * size, (i // cols) * (size + 22)
        sheet.paste(thumb, (x + 3, y + 20))
        draw.rectangle((x, y, x + size - 1, y + size + 21), outline="gray")
        draw.text((x + 4, y + 3), f"{i} p{r['paper']} d{r['conf']:.2f} {r['cls'][:7]} r{r['rconf']:.2f}", fill="black")
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEET)
    print("contact sheet:", SHEET.relative_to(REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
