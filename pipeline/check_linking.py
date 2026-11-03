"""Try label linking on the six internal papers with the Phase 1 boxes.

A development check, not a pipeline run. Regions and readings come from
Will's committed MolGlyph run on MolDetV2 boxes (233 boxes, no margin),
text from the PDF text layer or from OCR (pipeline/ocr_text.py), and there
are no tables yet. A link is confirmed when the answer key has that label
for the paper and its SMILES equals MolGlyph's reading of the box, and
wrong when the reading matches a different label's molecule. Needs the
course PDFs in data/internal/.

    python -m pipeline.check_linking

AI disclosure: Claude Code wrote this check at Jin's request.
"""
from __future__ import annotations

import csv
import re
import tempfile
from collections import Counter
from pathlib import Path

import pymupdf
from rdkit import Chem, RDLogger

from pipeline.linking import link_paper, read_jsonl, write_jsonl
from pipeline.smoke import READING_COLUMNS, REGION_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "benchmarks/results/willdaly/2026-10-06_moldetv2-molglyph-pad0_internal/predictions.csv"
KEY = ROOT / "data/internal/ground_truth_SMILES_confirmed_1,2,4,6,16,19.csv"
OCR_TEXT = ROOT / "data/liba-jin/ocr_text"
PAPERS = ["1", "2", "4", "6", "16", "19"]
COLUMNS = ["boxes", "linked", "confirmed", "wrong", "unchecked", "no label", "tie", "taken"]
RDLogger.DisableLog("rdApp.*")


def canonical(smiles: str) -> str | None:
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return Chem.MolToSmiles(mol) if mol else None


def text_records(pdf: Path, paper_id: str, unit: str) -> list[dict]:
    """Text records: the PDF text layer by block, line or word, or saved OCR lines."""
    if unit == "ocr":
        return read_jsonl(OCR_TEXT / f"{paper_id}.jsonl")
    records = []
    with pymupdf.open(pdf) as doc:
        for number, page in enumerate(doc, start=1):
            if unit == "word":
                items = [word[:5] for word in page.get_text("words")]
            elif unit == "line":
                items = [(*line["bbox"], "".join(span["text"] for span in line["spans"]))
                         for block in page.get_text("dict")["blocks"] if block["type"] == 0
                         for line in block["lines"]]
            else:
                items = [block[:5] for block in page.get_text("blocks") if block[6] == 0]
            for index, (x0, y0, x1, y1, text) in enumerate(items):
                records.append({"paper_id": paper_id, "page": number,
                                "block_id": f"{paper_id}-p{number}-{unit[0]}{index}",
                                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                                "text": text, "source": "pdf_text"})
    return records


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_inputs(folder: Path, paper_id: str, boxes: list[dict], text: list[dict]) -> None:
    """Stage files for one paper: Phase 1 boxes as regions, MolGlyph as the reader."""
    folder.mkdir(parents=True)
    write_jsonl(folder / "text.jsonl", text)
    write_jsonl(folder / "tables.jsonl", [])
    write_csv(folder / "regions.csv", REGION_COLUMNS, [
        {"paper_id": paper_id, "page": box["page"], "box_id": box["box_id"],
         "x0": box["x0"], "y0": box["y0"], "x1": box["x1"], "y1": box["y1"],
         "crop_path": "", "role": "unknown", "gate": "uncertain",
         "confidence": box["det_confidence"], "reason": "Phase 1 MolDetV2 box"}
        for box in boxes])
    write_csv(folder / "readings.csv", READING_COLUMNS, [
        {"paper_id": paper_id, "box_id": box["box_id"], "reader": "molglyph",
         "smiles": box["smiles"], "confidence": box["confidence"], "raw": "",
         "status": "ok" if box["smiles"] else "abstain", "reason": ""}
        for box in boxes])


def check_paper(folder: Path, boxes: list[dict], answers: dict[str, set]) -> Counter:
    """Count links by outcome for one paper."""
    reading = {box["box_id"]: canonical(box["smiles"]) for box in boxes}
    counts = Counter(boxes=len(boxes))
    for link in link_paper(folder):
        if link["status"] != "ok":
            reason = link["reason"]
            counts["tie" if "equally" in reason else "taken" if "closer" in reason else "no label"] += 1
            continue
        counts["linked"] += 1
        smiles = reading[link["box_id"]]
        if smiles and smiles in answers.get(link["label"], set()):
            counts["confirmed"] += 1
        elif smiles and any(smiles in found for name, found in answers.items() if name != link["label"]):
            counts["wrong"] += 1
        else:
            counts["unchecked"] += 1
    return counts


def main() -> None:
    with RUN.open(encoding="utf-8") as stream:
        boxes = list(csv.DictReader(stream))
    with KEY.open(encoding="utf-8") as stream:
        key = list(csv.DictReader(stream))
    units = ["block", "line", "word"] + (["ocr"] if OCR_TEXT.exists() else [])
    for unit in units:
        print(f"\nText: {'OCR lines' if unit == 'ocr' else 'one record per PDF ' + unit}")
        print(f"{'paper':>6}" + "".join(f"{name:>11}" for name in COLUMNS))
        total = Counter()
        with tempfile.TemporaryDirectory() as tmp:
            for paper_id in PAPERS:
                mine = [box for box in boxes if box["paper_id"] == paper_id]
                answers = {}
                for row in key:
                    if row["paperID"] == paper_id:
                        # The key sometimes writes "Compound 1h" for label 1h.
                        name = re.sub(r"(?i)^(compound|cmpd)\s+", "", row["name of molecule"].strip())
                        answers.setdefault(name, set()).add(canonical(row["canonical_SMILES"]))
                folder = Path(tmp) / "papers" / paper_id
                text = text_records(ROOT / "data/internal" / f"{paper_id}.pdf", paper_id, unit)
                write_inputs(folder, paper_id, mine, text)
                counts = check_paper(folder, mine, answers)
                total.update(counts)
                print(f"{paper_id:>6}" + "".join(f"{counts[name]:>11}" for name in COLUMNS))
        print(f"{'all':>6}" + "".join(f"{total[name]:>11}" for name in COLUMNS))


if __name__ == "__main__":
    main()
