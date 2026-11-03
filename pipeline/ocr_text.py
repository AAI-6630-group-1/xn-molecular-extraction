"""OCR the page images and write the text as text.jsonl records (source=ocr).

An experiment for label linking. In the internal papers, compound labels sit
inside figure images, so the PDF text layer misses them. This renders the
pages that hold the Phase 1 MolDetV2 boxes, runs RapidOCR on them, and maps
each text line back to PDF points the same way pipeline/smoke.py does.

It runs in its own environment, not the shared one:

    python -m venv .venv-ocr
    .venv-ocr/Scripts/pip install -r pipeline/requirements-ocr.txt
    .venv-ocr/Scripts/python -m pipeline.ocr_text --out data/liba-jin/ocr_text

AI disclosure: Claude Code wrote this experiment at Jin's request.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pymupdf
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "benchmarks/results/willdaly/2026-10-06_moldetv2-molglyph-pad0_internal/predictions.csv"
DPI = 300


def ocr_page(engine: RapidOCR, page: pymupdf.Page, paper_id: str, number: int) -> list[dict]:
    """OCR one page and return its text lines as text.jsonl records in PDF points."""
    scale = DPI / 72
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    transform = pymupdf.Matrix(1 / scale, 0, 0, 1 / scale,
                               pixmap.x / scale, pixmap.y / scale) * page.derotation_matrix
    result, _ = engine(np.ascontiguousarray(rgb[:, :, ::-1]))  # RapidOCR expects BGR
    records = []
    for index, (corners, text, score) in enumerate(result or []):
        points = [pymupdf.Point(x, y) * transform for x, y in corners]
        records.append({"paper_id": paper_id, "page": number,
                        "block_id": f"{paper_id}-p{number}-o{index}",
                        "x0": min(p.x for p in points), "y0": min(p.y for p in points),
                        "x1": max(p.x for p in points), "y1": max(p.y for p in points),
                        "text": text, "source": "ocr", "confidence": round(float(score), 3)})
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR the pages with Phase 1 boxes.")
    parser.add_argument("--out", type=Path, required=True, help="folder for <paper_id>.jsonl files")
    args = parser.parse_args()
    with RUN.open(encoding="utf-8") as stream:
        pages = sorted({(row["paper_id"], int(row["page"])) for row in csv.DictReader(stream)})
    args.out.mkdir(parents=True, exist_ok=True)
    engine = RapidOCR()
    for paper_id in sorted({paper for paper, _ in pages}, key=int):
        records = []
        with pymupdf.open(ROOT / "data/internal" / f"{paper_id}.pdf") as doc:
            for paper, number in pages:
                if paper == paper_id:
                    records += ocr_page(engine, doc[number - 1], paper_id, number)
        with (args.out / f"{paper_id}.jsonl").open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"paper {paper_id}: {len(records)} OCR lines")


if __name__ == "__main__":
    main()
