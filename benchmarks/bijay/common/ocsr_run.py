#!/usr/bin/env python3
"""Read BioVista OCSR crops with one reader and save the predictions in the team's format.

    python common/ocsr_run.py --reader decimer --crops-dir <folder of crop PNGs> --limit 20 --run-id smoke_decimer
    python common/ocsr_run.py --reader decimer --crops-dir <folder> --shard 0/4 --run-id 2026-10-18_decimer_biovista
    python common/merge_shards.py results/2026-10-18_decimer_biovista

Uses only the standard library, so it runs inside any reader's own environment; the reader
(<reader>/reader.py) is the part that needs the heavy dependencies. A reader module defines

    load(device: str) -> (predict, versions)
    predict(paths: list[Path]) -> [{"smiles": str, "confidence": float | None, "raw": str}, ...]

one dict per crop, in the order given. The output follows benchmarks/README.md ("Save each run
in its own folder") and is scored with benchmarks/score.py, as for benchmarks/willdaly/run_biovista.py.

--shard I/N reads every Nth crop starting at I, so N jobs can split the 8,861 crops; merge_shards.py
joins the parts. --resume keeps the rows already written, so an interrupted job picks up where it stopped.
A crop a reader fails on is written with an empty SMILES and the error in `raw`; the scorer counts it
as no output, and one bad crop doesn't kill a long run.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # benchmarks/bijay
READERS = sorted(p.name for p in ROOT.iterdir() if (p / "reader.py").exists())
COLUMNS = ["paper_id", "smiles", "confidence", "raw"]
RAW_LIMIT = 2000  # characters of the tool's untouched output kept per crop
MAX_FAILED_CHUNKS = 3  # stop after this many chunks in a row in which every crop failed


def parse_shard(text: str) -> tuple[int, int]:
    index, count = (int(part) for part in text.split("/"))
    if not 0 <= index < count:
        raise argparse.ArgumentTypeError("--shard must look like I/N with 0 <= I < N, e.g. 0/4")
    return index, count


def load_reader(name: str, device: str):
    """Import <name>/reader.py by path, so reader folders don't need to be packages."""
    spec = importlib.util.spec_from_file_location(f"xn_reader_{name}", ROOT / name / "reader.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load(device)


def git_commit() -> str:
    """Short commit of this code. XN_GIT_COMMIT wins, because a copy on the cluster has no .git."""
    if os.environ.get("XN_GIT_COMMIT"):
        return os.environ["XN_GIT_COMMIT"]
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    try:
        return git("rev-parse", "--short", "HEAD") + ("-dirty" if git("status", "--porcelain", "--untracked-files=no", "--", ".") else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def hardware() -> str:
    parts = [f"{platform.machine()} {platform.system()} {platform.release()}"]
    if os.environ.get("SLURMD_NODENAME"):
        parts.append(f"node {os.environ['SLURMD_NODENAME']}")
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=30).stdout.strip().splitlines()
        if gpu:
            parts.append(gpu[0])
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ", ".join(parts)


def read_chunk(predict, chunk: list[Path]) -> list[dict]:
    """Predict a batch; if that fails, retry crop by crop so one bad crop costs only itself."""
    try:
        preds = predict(chunk)
        if len(preds) != len(chunk):
            raise ValueError(f"reader returned {len(preds)} results for {len(chunk)} crops")
        return preds
    except Exception as exc:  # noqa: BLE001  any reader error, including CUDA out of memory
        print(f"  batch failed ({exc!r}); retrying crop by crop", flush=True)
    out = []
    for path in chunk:
        try:
            out.append(predict([path])[0])
        except Exception as exc:  # noqa: BLE001
            out.append({"smiles": "", "confidence": None, "raw": f"ERROR {type(exc).__name__}: {exc}"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reader", choices=READERS, required=True)
    ap.add_argument("--crops-dir", type=Path, required=True, help="folder of BioVista OCSR crop PNGs (ocsr/data)")
    ap.add_argument("--out-root", type=Path, default=ROOT / "results", help="runs go to <out-root>/<run-id>/")
    ap.add_argument("--run-id", help="default: <today>_<reader>_biovista")
    ap.add_argument("--handle", default="ArkAngel101", help="written to run.json")
    ap.add_argument("--device", default="cuda", help="cuda or cpu; each reader decides what it supports")
    ap.add_argument("--shard", type=parse_shard, default=(0, 1), metavar="I/N", help="read every Nth crop starting at I")
    ap.add_argument("--limit", type=int, help="use only the first N crops, before sharding (for a quick check)")
    ap.add_argument("--chunk", type=int, default=32, help="crops read between writes to predictions csv")
    ap.add_argument("--resume", action="store_true", help="keep the rows already written")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    crops = sorted(args.crops_dir.glob("*.png"))
    if not crops:
        sys.exit(f"no PNG crops in {args.crops_dir}")
    if args.limit:
        crops = crops[:args.limit]
    total = len(crops)
    shard, n_shards = args.shard
    crops = crops[shard::n_shards]

    tag = "" if n_shards == 1 else f".part{shard}of{n_shards}"
    run_id = args.run_id or f"{date.today().isoformat()}_{args.reader}_biovista"
    run_dir = args.out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    pred_path, run_path = run_dir / f"predictions{tag}.csv", run_dir / f"run{tag}.json"

    done: set[str] = set()
    if args.resume and pred_path.exists():
        with open(pred_path, newline="", encoding="utf-8") as f:
            done = {row["paper_id"] for row in csv.DictReader(f)}
    todo = [p for p in crops if p.stem not in done]
    print(f"{args.reader} shard {shard}/{n_shards}: {len(crops)} crops, {len(done)} already read, {len(todo)} to go", flush=True)

    predict, versions = load_reader(args.reader, args.device)
    t0 = time.perf_counter()
    failed_chunks = 0  # consecutive chunks where every crop errored: the reader, GPU or environment is broken
    with open(pred_path, "a" if done else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if not done:
            writer.writeheader()
        for start in range(0, len(todo), args.chunk):
            chunk = todo[start:start + args.chunk]
            preds = read_chunk(predict, chunk)
            failed_chunks = failed_chunks + 1 if all(str(p.get("raw", "")).startswith("ERROR") for p in preds) else 0
            if failed_chunks >= MAX_FAILED_CHUNKS:
                f.flush()
                sys.exit(f"stopping: {failed_chunks} chunks in a row failed on every crop. Last error: "
                         f"{str(preds[-1].get('raw', ''))[:300]}")
            for path, pred in zip(chunk, preds):
                conf = pred.get("confidence")
                writer.writerow({"paper_id": path.stem, "smiles": pred.get("smiles") or "",
                                 "confidence": "" if conf is None else round(float(conf), 4),
                                 "raw": str(pred.get("raw", ""))[:RAW_LIMIT]})
            f.flush()
            n = start + len(chunk)
            rate = (time.perf_counter() - t0) / n
            print(f"  {n}/{len(todo)} crops, {rate:.2f} s/crop, about {rate * (len(todo) - n) / 60:.0f} min left", flush=True)
    runtime = time.perf_counter() - t0

    previous = json.loads(run_path.read_text()) if done and run_path.exists() else {}
    run = {
        "handle": args.handle, "tool": args.reader, "track": 2, "task": "ocsr", "dataset": "biovista",
        "pipeline": f"{args.reader} on each BioVista OCSR crop as distributed (no extra margin or resizing)",
        "settings": {"n_crops": total, "shard": f"{shard}/{n_shards}", "device": args.device, "chunk": args.chunk},
        "versions": {"python": platform.python_version(), **versions},
        "command": " ".join(["python", *(shlex.quote(a) for a in sys.argv)]),
        "git_commit": git_commit(), "hardware": hardware(),
        # A resumed run adds this session's time to the earlier sessions'.
        "runtime_s": {"all": round(runtime + previous.get("runtime_s", {}).get("all", 0.0), 1)},
        "api_cost_usd": None, "notes": args.notes,
    }
    run_path.write_text(json.dumps(run, indent=2) + "\n")
    print(f"wrote {pred_path} and {run_path.name} ({len(todo)} crops, {runtime / 60:.1f} min this session)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
