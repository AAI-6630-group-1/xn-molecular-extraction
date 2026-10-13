#!/usr/bin/env python3
"""Track 2 benchmark: MolSight on molecule crops, written in the team's results format (#14).

Reads every crop of one dataset with MolSight (molsight_reader.py) and writes
predictions.csv and run.json to benchmarks/results/liba-jin/<run_id>/, ready for
benchmarks/score.py. The crops are the ones Will's MolScribe and MolGlyph runs
read, so the reader is the only thing that changes:

- biovista:  BioVista's 8,861 OCSR crops as distributed (download_data.py --biovista);
- patent300: the 2,482 ground-truth boxes of MolMole Patent300, cropped with no
             margin (make_crops.py --dataset patent300);
- internal:  MolDetV2's boxes on the six internal papers at 300 dpi with no margin,
             as in Will's moldetv2-*-pad0 runs (make_crops.py --dataset internal).
             This one is end to end: one SMILES per detected box, scored per paper.

Run it with the MolSight environment's Python (README.md, "Setup"):

    PY=benchmarks/liba-jin/.venv-molsight/Scripts/python.exe   # .venv-molsight/bin/python on macOS/Linux
    $PY benchmarks/liba-jin/run_molsight.py --dataset biovista --limit 50   # quick check
    $PY benchmarks/liba-jin/run_molsight.py --dataset biovista --variant stereo
    $PY benchmarks/liba-jin/run_molsight.py --dataset biovista --device cuda --batch-size 32   # NVIDIA GPU
    uv run python benchmarks/score.py benchmarks/results/liba-jin/<run_id>

Writes predictions.csv as it goes, so an interrupted run picks up where it
stopped with --resume.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from molsight_reader import VARIANTS, load_reader  # noqa: E402

CROPS = REPO / "data" / "liba-jin" / "crops"  # written by make_crops.py
CHUNK = 64  # crops read between writes to predictions.csv

# dataset -> (task, predictions.csv columns). The columns follow Will's runners so the scorers read
# them unchanged; `raw` (MolSight's untouched output) is extra and kept for error analysis.
DATASETS = {
    "biovista": ("ocsr", ["paper_id", "smiles", "confidence", "raw"]),
    "patent300": ("ocsr", ["paper_id", "smiles", "confidence", "raw"]),
    "internal": ("e2e", ["paper_id", "smiles", "page", "x0", "y0", "x1", "y1", "label", "source", "confidence",
                         "det_confidence", "box_id", "raw"]),
}
PIPELINES = {
    "biovista": "MolSight-{v} on each BioVista OCSR crop as distributed (no extra margin or resizing)",
    "patent300": "MolSight-{v} on each ground-truth box, cropped with a 0 px margin",
    "internal": ("PyMuPDF render at 300 dpi -> MolDetV2 boxes (conf >= 0.5) -> crop with 0 px margin "
                 "-> MolSight-{v} -> every box's SMILES"),
}


def load_crops(dataset: str) -> list[dict]:
    """One dict per crop: the image path plus the fields predictions.csv carries over (ids, page, box)."""
    if dataset == "biovista":
        folder = REPO / "data" / "biovista" / "ocsr" / "data"
        crops = [{"path": p, "paper_id": p.stem} for p in sorted(folder.glob("*.png"))]
        hint = "uv run python benchmarks/willdaly/download_data.py --biovista"
    else:
        index = CROPS / dataset / "index.csv"
        crops = []
        if index.exists():
            with open(index, newline="", encoding="utf-8") as f:
                crops = [{**row, "path": CROPS / dataset / f"{row['crop_id']}.png"} for row in csv.DictReader(f)]
        hint = f"uv run python benchmarks/liba-jin/make_crops.py --dataset {dataset}"
    if not crops:
        sys.exit(f"no {dataset} crops found; run: {hint}")
    return crops


def to_row(dataset: str, crop: dict, pred: dict) -> dict:
    out = {"paper_id": crop["paper_id"], "smiles": pred["smiles"], "confidence": round(pred["confidence"], 4),
           "raw": pred["raw"]}
    if dataset == "internal":
        out.update({k: crop[k] for k in ("page", "x0", "y0", "x1", "y1", "det_confidence")},
                   label="", source="drawing", box_id=crop["crop_id"])
    return out


def git_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()
    commit = git("rev-parse", "--short", "HEAD")
    return commit + ("-dirty" if git("status", "--porcelain", "--untracked-files=no", "--", "benchmarks") else "")


def hardware() -> str:
    """CPU, memory and OS for run.json."""
    cpu, mem_gb = platform.processor(), 0
    if platform.system() == "Windows":
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatus(dwLength=ctypes.sizeof(MemoryStatus))
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        mem_gb = round(status.ullTotalPhys / 2**30)
    elif platform.system() == "Darwin":
        def sysctl(key: str) -> str:
            return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True).stdout.strip()
        cpu, mem_gb = sysctl("machdep.cpu.brand_string"), int(sysctl("hw.memsize") or 0) // 2**30
    else:
        mem_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30)
    return f"{cpu}, {mem_gb} GB, {platform.system()} {platform.version()}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=DATASETS, required=True)
    ap.add_argument("--variant", choices=VARIANTS, default="extra", help="MolSight checkpoint (see molsight_reader.py)")
    ap.add_argument("--device", default="cpu", help="cpu, or cuda with the CUDA build of PyTorch (README.md)")
    ap.add_argument("--batch-size", type=int, default=16, help="crops per forward pass; 32 fits an 8 GB GPU")
    ap.add_argument("--limit", type=int, help="read only the first N crops (for a quick check)")
    ap.add_argument("--resume", action="store_true", help="keep the rows already in predictions.csv")
    ap.add_argument("--run-id", help="default: <today>_<tool>_<dataset>")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    task, columns = DATASETS[args.dataset]
    key = "box_id" if args.dataset == "internal" else "paper_id"
    crops = load_crops(args.dataset)
    crops = crops[:args.limit] if args.limit else crops

    tool = f"moldetv2-molsight-{args.variant}-pad0" if args.dataset == "internal" else f"molsight-{args.variant}"
    run_id = args.run_id or f"{date.today().isoformat()}_{tool}_{args.dataset}"
    run_dir = REPO / "benchmarks" / "results" / "liba-jin" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    pred_path = run_dir / "predictions.csv"

    done: set[str] = set()
    if args.resume and pred_path.exists():
        with open(pred_path, newline="", encoding="utf-8") as f:
            done = {row[key] for row in csv.DictReader(f)}
    todo = [c for c in crops if (c["crop_id"] if key == "box_id" else c["paper_id"]) not in done]
    print(f"{len(crops)} crops, {len(done)} already read, {len(todo)} to go", flush=True)

    reader = load_reader(args.variant, args.device, args.batch_size)
    t0 = time.perf_counter()
    with open(pred_path, "a" if done else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if not done:
            writer.writeheader()
        for start in range(0, len(todo), CHUNK):
            chunk = todo[start:start + CHUNK]
            images = [np.asarray(Image.open(c["path"]).convert("RGB")) for c in chunk]
            for crop, pred in zip(chunk, reader.predict(images)):
                writer.writerow(to_row(args.dataset, crop, pred))
            f.flush()
            n = start + len(chunk)
            rate = (time.perf_counter() - t0) / n
            print(f"  {n}/{len(todo)} crops, {rate:.2f} s/crop, about {rate * (len(todo) - n) / 60:.0f} min left",
                  flush=True)
    runtime = time.perf_counter() - t0

    previous = json.loads((run_dir / "run.json").read_text()) if done and (run_dir / "run.json").exists() else {}
    run = {
        "handle": "liba-jin", "tool": tool, "track": 2, "task": task, "dataset": args.dataset,
        "pipeline": PIPELINES[args.dataset].format(v=args.variant),
        "settings": {"variant": args.variant, "n_crops": len(crops), "device": args.device,
                     "batch_size": args.batch_size, "decoding": "greedy"},
        "versions": reader.versions,
        "command": "python " + " ".join(shlex.quote(a) for a in [
            Path(sys.argv[0]).resolve().relative_to(REPO).as_posix(), *sys.argv[1:]]),
        "git_commit": git_commit(), "hardware": f"{hardware()}, {args.device}",
        # Resumed runs add this session's time to the earlier sessions'.
        "runtime_s": {"all": round(runtime + previous.get("runtime_s", {}).get("all", 0.0), 1)},
        "api_cost_usd": None, "notes": args.notes,
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    print(f"wrote {run_dir.relative_to(REPO).as_posix()} ({len(crops)} crops, {runtime / 60:.1f} min this session)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
