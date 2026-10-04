#!/usr/bin/env python3
"""Track 3 benchmark: PDF pages -> MolDetV2 boxes -> MolScribe SMILES, for every internal paper.

Renders each page with PyMuPDF, detects molecule drawings with MolDetV2 (the 960 px
"doc" YOLO11n weights), crops each box with a margin, and reads every crop with
MolScribe (patched, see smoke_test_track3.py). Writes one run in the #14 results
format, ready for benchmarks/score.py:

    uv run python benchmarks/willdaly/run_track3.py
    uv run python benchmarks/willdaly/run_track3.py --dpi 200 --tool moldetv2-molscribe-200dpi
    uv run python benchmarks/score.py benchmarks/results/willdaly/<run_id>

The run folder (run.json, predictions.csv) is committed. Crops go to
data/track3_runs/<run_id>/, which is gitignored because they come from the papers;
each predictions.csv row's box_id names its crop file there.
"""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import platform
import shlex
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from smoke_test_track3 import patch_molscribe, render  # noqa: E402

PAPERS = ["1", "2", "4", "6", "16", "19"]
COLUMNS = ["paper_id", "smiles", "page", "x0", "y0", "x1", "y1", "label", "source", "confidence",
           "det_confidence", "box_id"]


def git_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()
    commit = git("rev-parse", "--short", "HEAD")
    return commit + ("-dirty" if git("status", "--porcelain", "--", "benchmarks/willdaly") else "")


def hardware() -> str:
    if platform.system() == "Darwin":
        def sysctl(key: str) -> str:
            return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True).stdout.strip()
        mem_gb = int(sysctl("hw.memsize") or 0) // 2**30
        return f"{sysctl('machdep.cpu.brand_string')} {mem_gb} GB, macOS {platform.mac_ver()[0]}"
    return f"{platform.machine()} {platform.system()} {platform.release()}"


def versions() -> dict[str, str]:
    out = {}
    for pkg in ("pymupdf", "ultralytics", "molscribe", "torch", "rdkit"):
        try:
            out[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    out["molscribe"] += " (GitHub 7296a30, patched)"
    out["moldetv2_weights"] = "UniParser/MolDetv2 moldet_v2_yolo11n_960_doc.pt"
    out["molscribe_weights"] = "yujieq/MolScribe swin_base_char_aux_1m.pth"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--papers", nargs="+", default=PAPERS)
    ap.add_argument("--dpi", type=int, default=300,
                    help="render resolution; the papers' raster figures are embedded at about 300 dpi")
    ap.add_argument("--conf", type=float, default=0.5, help="MolDetV2 confidence threshold (model card uses 0.5)")
    ap.add_argument("--pad", type=int, default=10, help="pixels added around each box before MolScribe")
    ap.add_argument("--device", default="cpu", help="cpu was faster than mps for MolScribe on an M1 Pro")
    ap.add_argument("--tool", default="moldetv2-molscribe", help="tool name in the run_id")
    ap.add_argument("--run-id", help="default: <today>_<tool>_internal")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    run_id = args.run_id or f"{date.today().isoformat()}_{args.tool}_internal"
    run_dir = REPO / "benchmarks" / "results" / "willdaly" / run_id
    crop_dir = REPO / "data" / "track3_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    det_w = hf_hub_download("UniParser/MolDetv2", "moldet_v2_yolo11n_960_doc.pt")
    ocsr_w = hf_hub_download("yujieq/MolScribe", "swin_base_char_aux_1m.pth")
    from molscribe import MolScribe
    from ultralytics import YOLO
    patch_molscribe()
    detector = YOLO(det_w)
    reader = MolScribe(ocsr_w, device=torch.device(args.device))

    rows, runtime, counts = [], {}, {}
    scale = 72 / args.dpi  # pixels -> PDF points
    for paper in args.papers:
        t0 = time.perf_counter()
        pages = render(REPO / "data" / "internal" / f"{paper}.pdf", args.dpi)
        boxes, crops = [], []
        for page_no, img in enumerate(pages, start=1):
            # Ultralytics treats numpy input as BGR, so flip the channels.
            result = detector.predict(img[..., ::-1], imgsz=960, conf=args.conf, device=args.device, verbose=False)[0]
            h, w, _ = img.shape
            for n, (xyxy, conf) in enumerate(zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist())):
                x0, y0, x1, y1 = xyxy
                box_id = f"{paper}-p{page_no}-{n}"
                crop = img[max(0, int(y0) - args.pad):min(h, int(y1) + args.pad),
                           max(0, int(x0) - args.pad):min(w, int(x1) + args.pad)]
                Image.fromarray(crop).save(crop_dir / f"{box_id}.png")
                boxes.append((box_id, page_no, x0, y0, x1, y1, conf))
                crops.append(crop)
        preds = reader.predict_images(crops, return_confidence=True, batch_size=8) if crops else []
        for (box_id, page_no, x0, y0, x1, y1, conf), pred in zip(boxes, preds):
            rows.append({
                "paper_id": paper, "smiles": pred["smiles"], "page": page_no,
                "x0": round(x0 * scale, 1), "y0": round(y0 * scale, 1),
                "x1": round(x1 * scale, 1), "y1": round(y1 * scale, 1),
                "label": "", "source": "drawing", "confidence": round(float(pred["confidence"]), 4),
                "det_confidence": round(conf, 4), "box_id": box_id,
            })
        runtime[paper] = round(time.perf_counter() - t0, 1)
        counts[paper] = {"pages": len(pages), "boxes": len(boxes)}
        print(f"paper {paper}: {len(pages)} pages, {len(boxes)} boxes, {runtime[paper]} s", flush=True)

    with open(run_dir / "predictions.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    run = {
        "handle": "willdaly",
        "tool": args.tool,
        "track": 3,
        "task": "e2e",
        "dataset": "internal",
        "pipeline": (f"PyMuPDF render at {args.dpi} dpi -> MolDetV2 boxes (conf >= {args.conf}) "
                     f"-> crop with {args.pad} px margin -> MolScribe (patched) -> every box's SMILES"),
        "settings": {"dpi": args.dpi, "det_conf": args.conf, "pad_px": args.pad, "device": args.device},
        "versions": versions(),
        "command": "uv run python " + " ".join(shlex.quote(a) for a in [str(Path(sys.argv[0]).resolve().relative_to(REPO)), *sys.argv[1:]]),
        "git_commit": git_commit(),
        "hardware": f"{hardware()}, {args.device}",
        "runtime_s": runtime,
        "counts": counts,
        "api_cost_usd": None,
        "notes": args.notes,
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    print(f"wrote {run_dir.relative_to(REPO)} ({len(rows)} predictions); crops in {crop_dir.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
