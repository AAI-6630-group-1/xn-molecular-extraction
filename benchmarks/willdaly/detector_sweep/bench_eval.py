#!/usr/bin/env python3
"""Run MolDetV2 on MolDet-Bench-Doc's labeled pages at several input sizes.

Downloads the 185 MB Doc zip to the gitignored data/moldet_bench/ folder (the
dataset is CC-BY-NC-SA-4.0, so it isn't committed), checks the developers' mAP50
with Ultralytics' val, and writes every box above conf 0.1. bench_score.py scores them.
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

from huggingface_hub import hf_hub_download
from PIL import Image
from ultralytics import YOLO

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "moldet_bench"
SET = DATA / "MolDet-Bench-Doc"
OUT = REPO / "benchmarks" / "results" / "willdaly" / "2026-11-06_moldetv2_moldet-bench-doc"


def fetch() -> None:
    """Unpack the Doc set once, and write our own YAML so paths point at this machine."""
    if not (SET / "images").is_dir():
        DATA.mkdir(parents=True, exist_ok=True)
        path = hf_hub_download("UniParser/MolDet-Bench", "doc/MolDet-Bench-Doc.zip", repo_type="dataset")
        with zipfile.ZipFile(path) as z:
            z.extractall(DATA)
    (DATA / "data.yaml").write_text(f"path: {SET}\ntrain: images\nval: images\nnc: 1\nnames: [molecule]\n")


def main() -> int:
    fetch()
    OUT.mkdir(parents=True, exist_ok=True)
    model = YOLO(hf_hub_download("UniParser/MolDetv2", "moldet_v2_yolo11n_960_doc.pt"))
    metrics = model.val(data=str(DATA / "data.yaml"), imgsz=960, split="val", classes=[0], device="cpu",
                        project=str(DATA / "val"), plots=False, verbose=False)
    print("val imgsz 960: mAP50", round(metrics.box.map50, 4), "mAP50-95", round(metrics.box.map, 4), flush=True)
    images = sorted((SET / "images").glob("*.png"))
    with open(OUT / "pages.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["page", "W", "H"])
        for path in images:
            writer.writerow([path.stem, *Image.open(path).size])
    with open(OUT / "pred.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow("imgsz page x0 y0 x1 y1 conf".split())
        for imgsz in (960, 1280, 1600):
            for path in images:
                result = model.predict(str(path), imgsz=imgsz, conf=0.1, device="cpu", verbose=False)[0]
                for box, conf in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()):
                    writer.writerow([imgsz, path.stem, *[round(v, 1) for v in box], round(conf, 4)])
            f.flush()
            print("done", imgsz, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
