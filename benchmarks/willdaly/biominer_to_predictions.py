#!/usr/bin/env python3
"""Turn one full-BioMiner run (hpc/biominer/run.sbatch) into two runs in the #14 results format.

- <date>_biominer_internal: the structures BioMiner reports. Its language model, BioMiner-Instruct,
  links each drawing to a compound label (the "full" rows) and expands scaffold-plus-R-group
  tables into one molecule per row (the "markush" rows). The `stage` column says which.
- <date>_biominer-stage1_internal: every box BioMiner's detection stage found (MolDetV2 on whole
  pages plus on MinerU's table crops), with MolGlyph's SMILES, before the language model. The gap
  between the two runs is what the language-model step adds.

Copy the run archive back from the cluster and convert it:

    ssh explorer 'cat /scratch/$USER/xn/biominer/runs/<run_id>.tar' | tar -C data/biominer_runs -xf -
    ssh explorer 'cat /scratch/$USER/xn/logs/xn-biominer-<jobid>.out' > data/biominer_runs/logs/slurm.out
    uv run python benchmarks/willdaly/biominer_to_predictions.py data/biominer_runs/out/<run_id> \\
        --slurm-log data/biominer_runs/logs/slurm.out
    uv run python benchmarks/score.py benchmarks/results/willdaly/<run_id>

The archive holds MinerU's text and page images from the papers, so it stays in the gitignored
data/; only the two run folders are committed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COLUMNS = ["paper_id", "smiles", "page", "x0", "y0", "x1", "y1", "label", "source", "stage", "box_id"]


def read_pins() -> dict[str, str]:
    """Pinned BioMiner commit, model revisions and key package versions, from hpc/biominer/."""
    pins = dict(re.findall(r"^export (\w+_(?:COMMIT|REV))=(\w+)", (REPO / "hpc/biominer/env.sh").read_text(), re.M))
    for env in ("main", "vllm"):
        locked = dict(re.findall(r"^([\w.-]+)(?:\[[\w,]+\])?==(\S+)", (REPO / f"hpc/biominer/{env}.lock.txt").read_text(), re.M))
        for package in ("torch", "transformers", "vllm", "magic-pdf", "ultralytics", "rdkit-pypi", "pdf2image"):
            if package in locked:
                pins[f"{package} ({env} env)"] = locked[package]
    return pins


def parse_slurm_log(path: Path | None) -> dict[str, str]:
    """Job id, node, GPU, repo commit, pipeline time and failed LLM calls from run.sbatch's log."""
    if path is None:
        return {}
    text = path.read_text()
    patterns = {
        "job": r"^job:\s+(\d+)",
        "node": r"^job:\s+\d+ \S+ on (\S+),",
        "gpu": r"^gpu:\s+(.+)$",
        "commit": r"^commit:\s+(\S+)",
        "pipeline_s": r"^pipeline: exit \d+ after (\d+) s",
        "pipeline_exit": r"^pipeline: exit (\d+)",
        "llm_failures": r"^llm calls that failed: (\d+)",
    }
    found = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.M)
        if m:
            found[key] = m.group(1).strip()
    return found


def read_structures(csv_path: Path) -> list[tuple[str, str]]:
    """(label, smiles) rows of one of BioMiner's structure CSVs; empty SMILES are dropped."""
    if not csv_path.exists():
        return []
    with open(csv_path, newline="") as f:
        return [(r["ligand"].strip(), r["smiles"].strip()) for r in csv.DictReader(f) if (r.get("smiles") or "").strip()]


def final_rows(out: Path, names: list[str]) -> list[dict]:
    """BioMiner's reported structures, tagged with the stage that produced them."""
    extraction = next(out.glob("extraction_*"), None)
    if extraction is None:
        raise SystemExit(f"no extraction_* folder in {out}; did the language-model stage run?")
    rows = []
    for name in names:
        paper = extraction / name
        for stage, pattern in (("full", f"{name}_structure_full_output_*.csv"), ("markush", f"{name}_structure_part_output_*.csv")):
            for csv_path in sorted(paper.glob(pattern)):
                for label, smiles in read_structures(csv_path):
                    rows.append({"paper_id": name, "smiles": smiles, "label": label, "source": "drawing", "stage": stage})
        # The merged file should be exactly the full rows plus the markush rows.
        merged = [p for p in paper.glob(f"{name}_structure_merged_output_*.csv")]
        if merged:
            ours = sorted((r["label"], r["smiles"]) for r in rows if r["paper_id"] == name)
            theirs = sorted(read_structures(merged[0]))
            if ours != theirs:
                print(f"warning: paper {name}: merged CSV has {len(theirs)} rows, full + markush have {len(ours)}", file=sys.stderr)
    return rows


def stage1_rows(ocsr_json: Path, names: list[str], pdf_dir: Path) -> list[dict]:
    """Every detected box with MolGlyph's SMILES, with the box converted to PDF points."""
    per_paper = json.loads(ocsr_json.read_text())
    rows = []
    for name, boxes in zip(names, per_paper):
        with fitz.open(pdf_dir / f"{name}.pdf") as doc:
            sizes = [(page.rect.width, page.rect.height) for page in doc]
        for box in boxes:
            page = int(box["page"])
            x, y, w, h = box["bbox"]  # fractions of the rendered page image
            width, height = sizes[page]
            rows.append({
                "paper_id": name, "smiles": box.get("smiles") or "", "page": page + 1,
                "x0": round(x * width, 1), "y0": round(y * height, 1),
                "x1": round((x + w) * width, 1), "y1": round((y + h) * height, 1),
                "source": "drawing", "stage": "stage1", "box_id": f"{name}-p{page + 1}-{box['index']}",
            })
    return rows


def check_pages(out: Path, names: list[str], pdf_dir: Path) -> dict[str, dict[str, int]]:
    """Compare rendered page images with the PDFs' page counts.

    BioMiner renders pages with pdf2image and returns no pages at all if that fails (for example
    when poppler is missing), so a paper can come out empty without any error.
    """
    counts = {}
    for name in names:
        with fitz.open(pdf_dir / f"{name}.pdf") as doc:
            pages = doc.page_count
        rendered = len(list((out / "page_images" / name).glob("*.png")))
        counts[name] = {"pages": pages, "rendered_pages": rendered}
        if rendered != pages:
            raise SystemExit(f"paper {name}: {rendered} page images for {pages} PDF pages; BioMiner didn't see the whole paper")
    return counts


def write_run(run_dir: Path, rows: list[dict], meta: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "predictions.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows([r for r in rows if r["smiles"]])
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    shown = run_dir.relative_to(REPO) if run_dir.is_relative_to(REPO) else run_dir
    print(f"wrote {shown} ({sum(1 for r in rows if r['smiles'])} SMILES)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("biominer_out", type=Path, help="the folder BioMiner wrote, data/biominer_runs/out/<run_id>")
    ap.add_argument("--slurm-log", type=Path, help="run.sbatch's Slurm log, for job, GPU and timing")
    ap.add_argument("--pdf-dir", type=Path, default=REPO / "data" / "internal")
    ap.add_argument("--results", type=Path, default=REPO / "benchmarks" / "results" / "willdaly")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    out = args.biominer_out.resolve()
    run_id = out.name                                    # <date>_<tool>_internal, from run.sbatch
    run_date, tool, dataset = run_id.split("_")
    ocsr_json = next(out.glob("*_ocsr_output.json"))
    task = ocsr_json.name.removesuffix("_ocsr_output.json")
    names = (out / f"{task}.txt").read_text().split()   # BioMiner's own paper order
    counts = check_pages(out, names, args.pdf_dir)
    final, stage1 = final_rows(out, names), stage1_rows(ocsr_json, names, args.pdf_dir)
    for name in names:
        counts[name]["boxes"] = sum(1 for r in stage1 if r["paper_id"] == name)
        counts[name]["full_rows"] = sum(1 for r in final if r["paper_id"] == name and r["stage"] == "full")
        counts[name]["markush_rows"] = sum(1 for r in final if r["paper_id"] == name and r["stage"] == "markush")

    log = parse_slurm_log(args.slurm_log)
    common = {
        "handle": "willdaly",
        "track": 1,
        "task": "e2e",
        "dataset": dataset,
        "settings": {"config": "BioMiner/config/default_open_source.yaml with hpc/biominer/biominer.patch (grounding_gpu_num 1)",
                     "vllm": "tensor-parallel 1, gpu-memory-utilization 0.75, max-model-len 65536",
                     "page_render": "pdf2image default (200 dpi)"},
        "versions": read_pins() | {"rdkit (scoring)": "2026.3.2"},
        "command": f"sbatch hpc/biominer/run.sbatch {' '.join(names)}",
        "git_commit": log.get("commit", ""),
        "hardware": f"Explorer {log.get('node', '?')}, {log.get('gpu', '?')}",
        "slurm_job": log.get("job", ""),
        "runtime_s": {"all_papers": int(log["pipeline_s"])} if "pipeline_s" in log else {},
        "counts": counts,
        "api_cost_usd": 0,
        "llm_failures": int(log["llm_failures"]) if "llm_failures" in log else None,
        "notes": args.notes,
    }
    write_run(args.results / run_id, final, {
        "tool": tool,
        "pipeline": "pdf2image pages -> MinerU layout -> MolDetV2 boxes on pages and table crops -> MolGlyph SMILES -> "
                    "BioMiner-Instruct links drawings to labels (stage full) and enumerates scaffold + R-group tables (stage markush)",
        **common,
    })
    write_run(args.results / f"{run_date}_{tool.replace('biominer', 'biominer-stage1', 1)}_{dataset}", stage1, {
        "tool": tool.replace("biominer", "biominer-stage1", 1),
        "pipeline": "pdf2image pages -> MinerU layout -> MolDetV2 boxes on pages and table crops -> MolGlyph SMILES for every box "
                    "(BioMiner's stage one, before the language model)",
        **common,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
