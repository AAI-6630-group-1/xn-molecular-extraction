#!/usr/bin/env python3
"""Write the molecule crops MolSight reads, for the datasets that aren't distributed as crops.

MolSight runs in its own environment, without PyMuPDF or Ultralytics, so the
crops are made here in the shared environment. They go to
data/liba-jin/crops/<dataset>/ as PNG files (gitignored, since they come from
the papers), with an index.csv that run_molsight.py reads.

- patent300: every ground-truth structure box in MolMole Patent300, cropped as
  annotated (no margin), as Will's run_patent300.py --tasks ocsr does.
- internal: each internal paper rendered at 300 dpi with PyMuPDF, MolDetV2 boxes
  with score >= 0.5, cropped with no margin, as Will's run_track3.py --pad 0
  does. His MolScribe and MolGlyph pad-0 runs read the same boxes, so all
  three readers see identical crops; the script checks the box ids against his
  run when it's there.

    uv run python benchmarks/liba-jin/make_crops.py                     # both datasets
    uv run python benchmarks/liba-jin/make_crops.py --dataset internal
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "data" / "liba-jin" / "crops"
WILL_PAD0 = REPO / "benchmarks" / "results" / "willdaly" / "2026-10-06_moldetv2-molglyph-pad0_internal"
sys.path.insert(0, str(HERE.parent))  # shared code: readers.py
sys.path.insert(0, str(HERE.parent / "willdaly"))  # Will's Track 3 helpers, reused so the crops match his


def write_index(folder: Path, rows: list[dict]) -> None:
    with open(folder / "index.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def patent300() -> None:
    from run_patent300 import DATA, crop, gt_boxes

    out = OUT / "patent300"
    out.mkdir(parents=True, exist_ok=True)
    rows, page, img = [], None, None
    for page_stem, crop_id, box in gt_boxes():
        if page_stem != page:  # gt_boxes() lists each page's boxes together
            page = page_stem
            img = np.asarray(Image.open(DATA / "images_300" / f"{page}.png").convert("RGB"))
        Image.fromarray(crop(img, box, 0)).save(out / f"{crop_id}.png")
        rows.append({"crop_id": crop_id, "paper_id": crop_id, "page": page})
    write_index(out, rows)
    print(f"patent300: {len(rows)} ground-truth crops in {out.relative_to(REPO).as_posix()}")


def internal(dpi: int = 300, conf: float = 0.5) -> None:
    from huggingface_hub import hf_hub_download
    from run_track3 import PAPERS
    from smoke_test_track3 import render
    from ultralytics import YOLO

    detector = YOLO(hf_hub_download("UniParser/MolDetv2", "moldet_v2_yolo11n_960_doc.pt"))
    out = OUT / "internal"
    out.mkdir(parents=True, exist_ok=True)
    scale = 72 / dpi  # pixels -> PDF points
    rows = []
    for paper in PAPERS:
        for page_no, img in enumerate(render(REPO / "data" / "internal" / f"{paper}.pdf", dpi), start=1):
            # Ultralytics treats numpy input as BGR, so flip the channels (as run_track3.py does).
            result = detector.predict(img[..., ::-1], imgsz=960, conf=conf, device="cpu", verbose=False)[0]
            h, w, _ = img.shape
            for n, (xyxy, score) in enumerate(zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist())):
                x0, y0, x1, y1 = xyxy
                box_id = f"{paper}-p{page_no}-{n}"
                crop = img[max(0, int(y0)):min(h, int(y1)), max(0, int(x0)):min(w, int(x1))]
                Image.fromarray(crop).save(out / f"{box_id}.png")
                rows.append({"crop_id": box_id, "paper_id": paper, "page": page_no,
                             "x0": round(x0 * scale, 1), "y0": round(y0 * scale, 1),
                             "x1": round(x1 * scale, 1), "y1": round(y1 * scale, 1),
                             "det_confidence": round(score, 4)})
        print(f"internal: paper {paper} done ({len(rows)} boxes so far)", flush=True)
    write_index(out, rows)
    print(f"internal: {len(rows)} MolDetV2 crops in {out.relative_to(REPO).as_posix()}")

    if (WILL_PAD0 / "predictions.csv").exists():
        with open(WILL_PAD0 / "predictions.csv", newline="", encoding="utf-8") as f:
            theirs = {row["box_id"] for row in csv.DictReader(f)}
        ours = {row["crop_id"] for row in rows}
        print(f"internal: {len(ours & theirs)} of {len(ours)} box ids match Will's pad-0 run "
              f"({len(theirs)} boxes there)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", nargs="+", choices=["patent300", "internal"], default=["patent300", "internal"])
    args = ap.parse_args()
    if "patent300" in args.dataset:
        patent300()
    if "internal" in args.dataset:
        internal()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
