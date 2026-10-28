"""Render one PDF and write empty Phase 2 handoffs without model inference.

AI disclosure: Codex wrote this scaffold and its tests for team review.
It checks plumbing, not extraction accuracy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import time
from pathlib import Path

import pymupdf

REGION_COLUMNS = "paper_id page box_id x0 y0 x1 y1 crop_path role gate confidence reason".split()
READING_COLUMNS = "paper_id box_id reader smiles confidence raw status reason".split()
PREDICTION_COLUMNS = (
    "paper_id smiles page x0 y0 x1 y1 label source confidence box_id "
    "prediction_id method evidence_id"
).split()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def empty_csv(path: Path, columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=columns).writeheader()


def git_revision() -> str:
    """Record the source revision without requiring a Git checkout."""
    try:
        root = Path(__file__).resolve().parents[1]
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render_document(doc: pymupdf.Document, out: Path, paper_id: str, dpi: int) -> tuple[int, int]:
    """Save page images/text and the matrix from rendered pixels to PDF points."""
    paper_dir = out / "papers" / paper_id
    (paper_dir / "pages").mkdir(parents=True)
    (paper_dir / "crops").mkdir()
    pages, blocks = [], []
    scale = dpi / 72
    for number, page in enumerate(doc, start=1):
        image_path = paper_dir / "pages" / f"{number:04d}.png"
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        pixmap.save(image_path)
        # Rendering applies rotation; text extraction does not. Include the
        # pixmap origin before undoing rotation instead of assuming scale only.
        transform = pymupdf.Matrix(1 / scale, 0, 0, 1 / scale,
                                   pixmap.x / scale, pixmap.y / scale) * page.derotation_matrix
        pages.append({
            "paper_id": paper_id, "page": number,
            "image_path": image_path.relative_to(out).as_posix(),
            "width_px": pixmap.width, "height_px": pixmap.height,
            "width_pt": page.rect.width, "height_pt": page.rect.height,
            "rotation": page.rotation, "dpi": dpi, "pixel_to_pdf": list(transform),
        })
        for x0, y0, x1, y1, text, block_number, block_type in page.get_text("blocks"):
            if block_type == 0:
                blocks.append({"paper_id": paper_id, "page": number,
                               "block_id": f"{paper_id}-p{number}-t{block_number}",
                               "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                               "text": text, "source": "pdf_text"})
    write_jsonl(paper_dir / "pages.jsonl", pages)
    write_jsonl(paper_dir / "text.jsonl", blocks)
    return len(pages), len(blocks)


def run_smoke(pdf: Path, paper_id: str, out: Path, dpi: int = 72) -> dict:
    """Write explicit stub files into a new directory; preserve an error manifest.

    Existing output directories are refused so no previous run can be replaced.
    Failures are recorded and re-raised rather than becoming empty predictions.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", paper_id):
        raise ValueError("paper_id must be a simple identifier, not a path")
    if not 36 <= dpi <= 300:
        raise ValueError("smoke DPI must be between 36 and 300")
    pdf = pdf.resolve(strict=True)
    started = time.perf_counter()
    with pymupdf.open(pdf) as doc:
        if not doc.is_pdf or doc.needs_pass or len(doc) == 0:
            raise ValueError("input must be a readable, nonempty, unencrypted PDF")
        out.mkdir(parents=True, exist_ok=False)
        meta = {
            "schema_version": "0.1", "task": "smoke", "dataset": "pipeline-smoke",
            "tool": "phase2-interface-smoke", "paper_ids": [paper_id],
            "input_file": pdf.name, "input_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "git_commit": git_revision(), "hardware": f"{platform.machine()} CPU",
            "versions": {"python": platform.python_version(),
                         "pymupdf": importlib.metadata.version("pymupdf")},
            "command": ["python", "-m", "pipeline.smoke", "--pdf", str(pdf),
                        "--paper-id", paper_id, "--out", str(out), "--dpi", str(dpi)],
            "status": "running", "stages": {},
            "notes": "Rendering/text are real. All extraction stages are stubs; do not score.",
        }
        try:
            count, text_count = render_document(doc, out, paper_id, dpi)
            meta["stages"]["render_text"] = {
                "status": "complete", "pages": count, "text_blocks": text_count}
            paper_dir = out / "papers" / paper_id
            empty_csv(paper_dir / "regions.csv", REGION_COLUMNS)
            write_jsonl(paper_dir / "tables.jsonl", [])
            empty_csv(paper_dir / "readings.csv", READING_COLUMNS)
            write_jsonl(paper_dir / "links.jsonl", [])
            write_jsonl(paper_dir / "assemblies.jsonl", [])
            empty_csv(out / "predictions.csv", PREDICTION_COLUMNS)
            write_jsonl(out / "provenance.jsonl", [])
            write_jsonl(out / "export_rejections.jsonl", [])
            for stage in ("detect_gate_tables", "read_consensus", "link", "assemble", "export"):
                meta["stages"][stage] = {"status": "stub", "records": 0,
                                          "reason": "not implemented in the smoke runner"}
            meta["status"] = "smoke_complete"
        except Exception as error:
            meta["status"] = "error"
            meta["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            meta["runtime_s"] = round(time.perf_counter() - started, 3)
            (out / "run.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=72)
    args = parser.parse_args()
    meta = run_smoke(args.pdf, args.paper_id, args.out, args.dpi)
    print(f"Rendered {meta['stages']['render_text']['pages']} pages; extraction stages are STUBS.")
    print(f"Files: {args.out}; no extraction metrics produced.")


if __name__ == "__main__":
    main()
