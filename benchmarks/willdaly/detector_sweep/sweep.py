#!/usr/bin/env python3
"""Detector sweep on the six internal papers: input size, confidence floor, and tiling.

Stores every box above a low confidence floor in page pixels (300 dpi), so any
higher threshold can be applied afterwards without rerunning the model. The
first config is the baseline from run_track3.py (imgsz 960, whole page).
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import torch
import torchvision
from huggingface_hub import hf_hub_download
from ultralytics import YOLO

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "benchmarks"))
sys.path.insert(0, str(REPO / "benchmarks" / "willdaly"))
from smoke_test_track3 import render  # noqa: E402

OUT = REPO / "benchmarks" / "results" / "willdaly" / "2026-11-06_detector-sweep_internal"
PAPERS = ["1", "2", "4", "6", "16", "19"]
CONF_FLOOR = 0.10
DPI = 300
# (name, imgsz, tile_px). tile_px 0 is the whole page; otherwise overlapping square tiles.
CONFIGS = [
    ("page960", 960, 0),
    ("page1280", 1280, 0),
    ("page1600", 1600, 0),
    ("page1920", 1920, 0),
    ("tile1600", 960, 1600),
]
TILE_OVERLAP = 400  # px; wide enough that most drawings sit whole inside at least one tile


def tiles(h: int, w: int, size: int) -> list[tuple[int, int]]:
    """Top-left corners of overlapping tiles that cover an h by w page."""
    step = size - TILE_OVERLAP
    ys = list(range(0, max(h - size, 0) + 1, step))
    xs = list(range(0, max(w - size, 0) + 1, step))
    if ys[-1] + size < h:
        ys.append(h - size)
    if xs[-1] + size < w:
        xs.append(w - size)
    return [(y, x) for y in ys for x in xs]


def detect(model: YOLO, img, imgsz: int, tile_px: int) -> list[tuple[float, float, float, float, float]]:
    """Boxes as (x0, y0, x1, y1, conf) in page pixels."""
    h, w, _ = img.shape
    if not tile_px:
        r = model.predict(img[..., ::-1], imgsz=imgsz, conf=CONF_FLOOR, device="cpu", verbose=False)[0]
        return [(*xyxy, c) for xyxy, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist())]
    found = []
    for y, x in tiles(h, w, tile_px):
        crop = img[y:y + tile_px, x:x + tile_px]
        r = model.predict(crop[..., ::-1], imgsz=imgsz, conf=CONF_FLOOR, device="cpu", verbose=False)[0]
        for (x0, y0, x1, y1), c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist()):
            found.append((x0 + x, y0 + y, x1 + x, y1 + y, c))
    if not found:
        return []
    # The same drawing appears in neighbouring tiles, so merge across tiles.
    t = torch.tensor(found)
    keep = torchvision.ops.nms(t[:, :4], t[:, 4], 0.5).tolist()
    return [found[i] for i in keep]


def main() -> int:
    model = YOLO(hf_hub_download("UniParser/MolDetv2", "moldet_v2_yolo11n_960_doc.pt"))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "boxes.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["config", "paper_id", "page", "x0", "y0", "x1", "y1", "conf"])
        for paper in PAPERS:
            pages = render(REPO / "data" / "internal" / f"{paper}.pdf", DPI)
            for name, imgsz, tile_px in CONFIGS:
                t0 = time.perf_counter()
                n = 0
                for page_no, img in enumerate(pages, start=1):
                    for x0, y0, x1, y1, c in detect(model, img, imgsz, tile_px):
                        writer.writerow([name, paper, page_no, round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1),
                                         round(c, 4)])
                        n += 1
                f.flush()
                print(f"paper {paper} {name}: {len(pages)} pages, {n} boxes >= {CONF_FLOOR}, "
                      f"{time.perf_counter() - t0:.1f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
