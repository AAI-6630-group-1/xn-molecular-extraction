"""Front end for the Phase 2 pipeline: pages, text, candidate molecule regions and raw table geometry.

Implements the "front end, detection and filter" stage of pipeline/INTERFACES.md (contract 0.1). For every
paper it writes, under <out>/papers/<paper_id>/:

    pages.jsonl, text.jsonl    page images, the pixel-to-PDF matrix and native PDF text (pipeline/smoke.py)
    regions.csv, crops/        MolDetV2 candidates with a gate (molecule / uncertain / non_molecule) and crops
    tables.jsonl               raw table geometry and cell text, linked to regions and text blocks

and <out>/run.json (versions, settings, PDF hashes, a status for each stage). Reading, linking, assembly and
export belong to other owners and are not written here. Run from the repo root:

    uv run python -m pipeline.frontend --out data/pipeline_runs/frontend-all
    uv run python -m pipeline.frontend --pdf data/internal/2.pdf --paper-id 2 --out data/pipeline_runs/frontend-paper2
    uv run python -m pipeline.frontend --papers 2 4 19 --skip-detection --out data/pipeline_runs/tables-only
    uv run python -m pipeline.frontend --check data/pipeline_runs/frontend-all

Choices that INTERFACES.md leaves open are marked DECISION so the team can confirm or change them.

AI disclosure: Claude (Anthropic) drafted this module and its tests for Peter Adranly. The detector call follows
benchmarks/willdaly/run_track3.py. Read and run it before relying on it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

from pipeline.smoke import REGION_COLUMNS, git_revision, render_document, write_jsonl

REPO = Path(__file__).resolve().parents[1]
PAPERS = ["1", "2", "4", "6", "16", "19"]
Box = tuple[float, float, float, float]

# DECISION: padded crop coordinates are extra regions.csv columns after the contract's required ones
# (INTERFACES.md asks for separate crop coordinates when padding enlarges a detection).
CROP_COLUMNS = ["crop_x0", "crop_y0", "crop_x1", "crop_y1"]
REGION_FIELDS = REGION_COLUMNS + CROP_COLUMNS

VALID_GATES = {"molecule", "non_molecule", "uncertain"}
VALID_STATUS = {"ok", "abstain", "error"}
TABLE_KEYS = ("paper_id", "page", "table_id", "bbox", "scaffold_box_id", "columns", "rows", "status", "reason")
# DECISION: two extra keys beyond the contract, always present (null when unknown): the table's caption text and
# its footnote lines. The linker needs the caption to match "Table 3" mentions in the text.
TABLE_EXTRA_KEYS = ("caption", "notes")
COLUMN_KEYS = ("column_id", "heading")
ROW_KEYS = ("row_id", "label", "cells")
CELL_KEYS = ("cell_id", "column_id", "text", "box_id", "bbox", "evidence_block_ids")

# DECISION: gate thresholds are placeholders. Tune them on Patent300, not on the six internal papers.
MIN_SIDE_PX = 16        # a box with a shorter side is not a drawing (substituent cells are about 55 px wide at 300 dpi)
MAX_ASPECT = 15.0       # rules, borders and underlines
SCAFFOLD_MAX_GAP_PT = 200.0
SCAFFOLD_AMBIGUITY_PT = 10.0


# ---------------------------------------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Detection:
    """One detector box in pixels of the rendered page image."""
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


@dataclass
class RawCell:
    text: str                      # "" when the cell holds no text
    bbox: Box | None               # None for a merged or missing cell


@dataclass
class RawTable:
    bbox: Box
    grid: list[list[RawCell]]      # row 0 is treated as the header row
    caption: str | None = None     # "Table 3. ..." text when the table was found from its caption
    notes: str | None = None       # footnote lines under the table
    block: Box | None = None       # caption through closing rule; scaffold drawings are looked for inside it
    reason: str | None = None      # set when a table was seen but could not be built: it becomes an abstain record


@dataclass
class Settings:
    dpi: int = 300                 # run_track3.py default; the papers' raster figures sit at about 300 dpi
    conf: float = 0.5              # accept threshold: Will's sweep found nothing better than 960 px / 0.5
    floor: float | None = None     # detector floor; boxes between floor and conf become "uncertain"
    pad: int = 10                  # pixels added around each box for the crop
    device: str = "cpu"
    table_strategy: str = "lines"  # "lines", "lines_strict", "text" (PyMuPDF find_tables) or "captions" (see below)
    vertical_strategy: str | None = None    # set either of these two to choose the strategies separately
    horizontal_strategy: str | None = None
    skip_detection: bool = False   # tables only: no regions, so no cell box_id and no scaffold_box_id

    def __post_init__(self) -> None:
        if self.floor is None:
            self.floor = self.conf


# ---------------------------------------------------------------------------------------------------------
# Detector (the only part that needs the model stack; tests inject a fake)
# ---------------------------------------------------------------------------------------------------------
class MolDetV2Detector:
    """MolDetV2 (YOLO11n, 960 px "doc" weights) through Ultralytics, as in benchmarks/willdaly/run_track3.py."""

    WEIGHTS = ("UniParser/MolDetv2", "moldet_v2_yolo11n_960_doc.pt")

    def __init__(self, conf_floor: float, device: str = "cpu") -> None:
        from huggingface_hub import hf_hub_download  # imported here so tests and --skip-detection need no models
        from ultralytics import YOLO

        self.model = YOLO(hf_hub_download(*self.WEIGHTS))
        self.conf_floor, self.device = conf_floor, device

    def __call__(self, image: np.ndarray) -> list[Detection]:
        # Ultralytics treats numpy input as BGR, so flip the RGB channels (as run_track3.py does).
        result = self.model.predict(image[..., ::-1], imgsz=960, conf=self.conf_floor, device=self.device,
                                    verbose=False)[0]
        return [Detection(*xyxy, conf) for xyxy, conf in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist())]


# ---------------------------------------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------------------------------------
def apply_matrix(matrix: list[float], x: float, y: float) -> tuple[float, float]:
    """x' = a*x + c*y + e, y' = b*x + d*y + f (the contract's pixel_to_pdf convention)."""
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def transform_box(box: Box, matrix: list[float]) -> Box:
    """Transform all four corners, then take min/max, so rotated pages stay correct."""
    x0, y0, x1, y1 = box
    corners = [apply_matrix(matrix, x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    return min(xs), min(ys), max(xs), max(ys)


pixel_box_to_pdf = transform_box   # the same operation, named for its main use: rendered pixels -> PDF points


def rounded(box: Box, digits: int = 2) -> Box:
    return tuple(round(float(v), digits) for v in box)  # type: ignore[return-value]


def area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def overlap_fraction(inner: Box, outer: Box) -> float:
    """Share of `inner`'s area that lies inside `outer`."""
    width = min(inner[2], outer[2]) - max(inner[0], outer[0])
    height = min(inner[3], outer[3]) - max(inner[1], outer[1])
    if width <= 0 or height <= 0 or area(inner) == 0:
        return 0.0
    return width * height / area(inner)


def box_gap(a: Box, b: Box) -> float:
    """Distance between two rectangles (0 when they touch or overlap)."""
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    return math.hypot(dx, dy)


# ---------------------------------------------------------------------------------------------------------
# Gate and regions
# ---------------------------------------------------------------------------------------------------------
def gate_detection(det: Detection, accept: float, min_side_px: float = MIN_SIDE_PX,
                   max_aspect: float = MAX_ASPECT) -> tuple[str, str | None]:
    """Return (gate, reason). Rejected regions are kept as non_molecule with a reason, never dropped."""
    width, height = det.x1 - det.x0, det.y1 - det.y0
    if min(width, height) <= 0:
        return "non_molecule", "empty box"
    if min(width, height) < min_side_px:
        return "non_molecule", f"box side under {min_side_px:g} px"
    if max(width, height) / min(width, height) > max_aspect:
        return "non_molecule", f"aspect ratio over {max_aspect:g}:1"
    if det.confidence >= accept:
        return "molecule", None
    return "uncertain", f"detector confidence {det.confidence:.2f} below {accept:g}"


def make_regions(paper_id: str, page_no: int, page: dict, detections: list[Detection], accept: float,
                 pad: int) -> list[tuple[dict, tuple[int, int, int, int] | None]]:
    """One (regions.csv record, crop pixel box or None) per detection, in detector order.

    box_id is <paper>-p<page>-<n> with n the detector's output index, the same as Track 3's IDs. Coordinates
    are PDF points (unrotated); the crop pixel box is for cutting the page image.
    """
    matrix = page["pixel_to_pdf"]
    out = []
    for n, det in enumerate(detections):
        box_id = f"{paper_id}-p{page_no}-{n}"
        gate, reason = gate_detection(det, accept)
        x0, y0, x1, y1 = rounded(pixel_box_to_pdf((det.x0, det.y0, det.x1, det.y1), matrix))
        record = {"paper_id": paper_id, "page": page_no, "box_id": box_id, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                  "crop_path": "", "role": "unknown", "gate": gate, "confidence": round(det.confidence, 4),
                  "reason": reason or "", "crop_x0": "", "crop_y0": "", "crop_x1": "", "crop_y1": ""}
        crop_px = None
        if gate != "non_molecule":
            crop_px = (max(0, int(det.x0) - pad), max(0, int(det.y0) - pad),
                       min(page["width_px"], int(det.x1) + pad), min(page["height_px"], int(det.y1) + pad))
            cx0, cy0, cx1, cy1 = rounded(pixel_box_to_pdf(crop_px, matrix))
            record.update(crop_path=f"papers/{paper_id}/crops/{box_id}.png",
                          crop_x0=cx0, crop_y0=cy0, crop_x1=cx1, crop_y1=cy1)
        out.append((record, crop_px))
    return out


# ---------------------------------------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------------------------------------
def raw_tables_from_page(page, strategy: str = "lines", vertical: str | None = None,
                         horizontal: str | None = None) -> list[RawTable]:
    """Find tables with PyMuPDF and return their cell grid. Kept thin: everything after this is plain Python.

    find_tables reports coordinates as the page is displayed (rotated), but the contract and the text blocks use
    unrotated coordinates, so every box is mapped back with the page's derotation matrix (the identity when the
    page is not rotated). A real-PDF test showed this: on a 90 degree page the table box came back rotated.
    """
    unrotate = list(page.derotation_matrix)
    if vertical or horizontal:   # e.g. horizontal="lines", vertical="text" for journal tables with only horizontal rules
        options = {"vertical_strategy": vertical or "lines", "horizontal_strategy": horizontal or "lines"}
    else:
        options = {"strategy": strategy}
    tables = []
    for table in page.find_tables(**options).tables:
        text_rows = table.extract()
        grid = []
        for i, row in enumerate(table.rows):
            cells = []
            for j, bbox in enumerate(row.cells):
                value = text_rows[i][j] if i < len(text_rows) and j < len(text_rows[i]) else None
                cells.append(RawCell(text=str(value).strip() if value else "",
                                     bbox=transform_box(tuple(float(v) for v in bbox), unrotate) if bbox else None))
            grid.append(cells)
        tables.append(RawTable(bbox=transform_box(tuple(float(v) for v in table.bbox), unrotate), grid=grid))
    return tables


def blocks_in_cell(blocks: list[dict], cell: Box, min_overlap: float = 0.5) -> list[str]:
    """IDs of the text blocks that hold the cell's text, in reading order.

    A block belongs to the cell when most of the block lies inside it, or when the block covers most of the cell.
    The second case matters: PyMuPDF often groups a whole table row or header into one block that spans several
    cells, and that block is then evidence for each of them.
    """
    chosen = []
    for b in blocks:
        box = (b["x0"], b["y0"], b["x1"], b["y1"])
        if overlap_fraction(box, cell) >= min_overlap or overlap_fraction(cell, box) >= min_overlap:
            chosen.append(b)
    return [b["block_id"] for b in sorted(chosen, key=lambda b: (b["y0"], b["x0"]))]


def box_in_cell(regions: list[dict], cell: Box, min_overlap: float = 0.5) -> str | None:
    """The molecule/uncertain region that lies mostly inside the cell (a drawing in a table cell), else None."""
    best = None
    for r in regions:
        if r["gate"] not in ("molecule", "uncertain"):
            continue
        share = overlap_fraction((r["x0"], r["y0"], r["x1"], r["y1"]), cell)
        if share >= min_overlap and (best is None or share > best[0]):
            best = (share, r["box_id"])
    return best[1] if best else None


def pick_scaffold(regions: list[dict], table: Box, within: Box | None = None) -> str | None:
    """DECISION: heuristic scaffold guess, the nearest molecule region outside the table within 200 pt.

    Returns None when nothing is close or two candidates are about equally near. Label linking (Jin) makes
    the real association; the contract allows null here.
    """
    candidates = []
    for r in regions:
        box = (r["x0"], r["y0"], r["x1"], r["y1"])
        if r["gate"] != "molecule" or overlap_fraction(box, table) >= 0.5:
            continue
        if within is not None and overlap_fraction(box, within) < 0.5:
            continue                      # only drawings inside the table's own block (caption to closing rule)
        gap = box_gap(box, table)
        if gap <= SCAFFOLD_MAX_GAP_PT:
            candidates.append((gap, r["box_id"]))
    candidates.sort()
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < SCAFFOLD_AMBIGUITY_PT:
        return None
    return candidates[0][1]


def table_record(paper_id: str, page_no: int, index: int, raw: RawTable, blocks: list[dict],
                 regions: list[dict]) -> dict:
    """Build one tables.jsonl record. Every contract field is present; unavailable values are null.

    DECISION: row 0 of the grid is the header row. A row's `label` is the raw text of its first cell (often the
    compound number); deciding what it means is the linker's and assembler's job. row_id is r<grid row>
    (so the first data row is r1), cell_id is r<row>c<column>.
    """
    page_blocks = [b for b in blocks if b["page"] == page_no]
    page_regions = [r for r in regions if r["page"] == page_no]
    grid = raw.grid
    n_cols = max((len(row) for row in grid), default=0)
    header = grid[0] if grid else []
    columns = [{"column_id": f"c{j}", "heading": (header[j].text or None) if j < len(header) else None}
               for j in range(n_cols)]

    has_text, matched = False, False
    rows = []
    for i, row in enumerate(grid):
        cells = []
        for j, cell in enumerate(row):
            evidence = blocks_in_cell(page_blocks, cell.bbox) if cell.bbox else []
            has_text = has_text or bool(cell.text)
            matched = matched or bool(evidence)
            if i == 0:
                continue  # header cells feed the checks above and the column headings
            cells.append({"cell_id": f"r{i}c{j}", "column_id": f"c{j}", "text": cell.text,
                          "box_id": box_in_cell(page_regions, cell.bbox) if cell.bbox else None,
                          "bbox": list(rounded(cell.bbox)) if cell.bbox else None,
                          "evidence_block_ids": evidence})
        if i > 0:
            rows.append({"row_id": f"r{i}", "label": (row[0].text or None) if row else None, "cells": cells})

    if raw.reason:
        status, reason = "abstain", raw.reason
    elif len(grid) < 2 or n_cols < 2:
        status, reason = "abstain", "table has fewer than two rows or two columns"
    elif not has_text:
        status, reason = "abstain", "no text found in the table cells"
    elif not matched:
        status, reason = "abstain", ("cell text found but no text block overlaps the cells; the coordinates or "
                                     "the block granularity do not match the text blocks")
    else:
        status, reason = "ok", None
    return {"paper_id": paper_id, "page": page_no, "table_id": f"{paper_id}-p{page_no}-tab{index}",
            "bbox": list(rounded(raw.bbox)), "scaffold_box_id": pick_scaffold(page_regions, raw.bbox, raw.block),
            "columns": columns, "rows": rows, "status": status, "reason": reason,
            "caption": raw.caption, "notes": raw.notes}


# ---------------------------------------------------------------------------------------------------------
# Caption-anchored tables (journal tables whose rules are drawn in pieces and whose rows have no lines)
# ---------------------------------------------------------------------------------------------------------
CAPTION_TABLE = re.compile(r"^\s*Table\s+S?\d+\.")
CAPTION_ANY = re.compile(r"^\s*(Table|Figure|Scheme|Chart)\s+S?\d+\.")
RULE_TOL = 0.75            # pt: rule pieces closer than this in y are one rule (rectangles draw each edge)
MIN_RULE_WIDTH = 15.0
FULL_WIDTH = 0.9           # a header rule must cover this share of the closing rule's width
CLOSING_WIDTH = 0.8        # the closing rule must be this share of the caption's width
SENTENCE_GAP = 8.0         # pt: words closer than this all along a line make it running text (a footnote)
FOOTNOTE_MARKER = re.compile(r"^([a-z](?=[A-Z])|[*\u2020\u2021\u00a7#])")   # "aLigands", "bNone.", "*Not", dagger, section sign


@dataclass
class TableLayout:
    top_y: float
    header_bottom_y: float
    closing_y: float
    columns: list[tuple[float, float]]      # one x-range per column, from the header-bottom rule's pieces
    group_spans: list[tuple[float, float]]  # header cells on the top rule (a cell can span several columns)
    inner_ys: list[float]                   # rules between top and header bottom (group-header underlines)


def collect_rule_pieces(page) -> list[tuple[float, float, float]]:
    """Horizontal rule pieces (y, x0, x1) from the segments and thin rectangles inside every drawing path."""
    pieces = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) <= 0.5 and abs(p2.x - p1.x) >= MIN_RULE_WIDTH:
                    pieces.append(((p1.y + p2.y) / 2, min(p1.x, p2.x), max(p1.x, p2.x)))
            elif kind in ("re", "qu"):
                rect = item[1] if kind == "re" else item[1].rect
                if rect.height <= 2.5 and rect.width >= MIN_RULE_WIDTH:
                    pieces.append((rect.y0, rect.x0, rect.x1))
    return pieces


def merged_width(spans: list[tuple[float, float]]) -> float:
    total, end = 0.0, None
    for x0, x1 in sorted(spans):
        if end is None or x0 > end:
            total += x1 - x0
            end = x1
        elif x1 > end:
            total += x1 - end
            end = x1
    return total


def normalize_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Clean the pieces of one rule: drop a wide piece that is just the union of narrower ones (a rectangle edge drawn
    beside per-column segments), then merge pieces that are the same piece drawn twice."""
    spans = sorted(spans)
    kept = [s for s in spans if sum(1 for o in spans if o != s and o[0] >= s[0] - 0.6 and o[1] <= s[1] + 0.6) < 2]
    merged: list[tuple[float, float]] = []
    for x0, x1 in kept:
        if merged:
            px0, px1 = merged[-1]
            if min(px1, x1) - max(px0, x0) > 0.5 * min(px1 - px0, x1 - x0):
                merged[-1] = (min(px0, x0), max(px1, x1))
                continue
        merged.append((x0, x1))
    return merged


def rule_groups(pieces: list[tuple[float, float, float]], tol: float = RULE_TOL) -> list[dict]:
    """Group rule pieces that sit at (nearly) the same height into rules, top to bottom."""
    grouped: list[list[tuple[float, float, float]]] = []
    for piece in sorted(pieces):
        if grouped and piece[0] - grouped[-1][-1][0] <= tol:
            grouped[-1].append(piece)
        else:
            grouped.append([piece])
    rules = []
    for items in grouped:
        spans = normalize_spans([(p[1], p[2]) for p in items])
        rules.append({"y": sum(p[0] for p in items) / len(items), "spans": spans,
                      "x0": min(s[0] for s in spans), "x1": max(s[1] for s in spans), "coverage": merged_width(spans)})
    return rules


def x_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def next_caption_below(caption: dict, captions: list[dict]) -> float | None:
    """y of the nearest caption below this one in the same column. A caption in the other column of a two-column page
    does not bound this table (paper 19 page 8: a left-column figure caption sat above a right-column table's rules)."""
    width = caption["x1"] - caption["x0"]
    ys = [c["y0"] for c in captions if c["y0"] > caption["y1"]
          and x_overlap(c["x0"], c["x1"], caption["x0"], caption["x1"]) >= 0.2 * min(width, c["x1"] - c["x0"])]
    return min(ys) if ys else None


def same_extent(rule: dict, other: dict, tol: float = 2.0) -> bool:
    return abs(rule["x0"] - other["x0"]) <= tol and abs(rule["x1"] - other["x1"]) <= tol


def locate_table(caption: Box, rules: list[dict], next_caption_y: float | None = None) -> tuple[TableLayout | None, str | None]:
    """Find a table's rules below its caption. Returns (layout, None) or (None, reason).

    Journal tables have a top rule and a header-bottom rule drawn in one piece per column, then body rows (sometimes
    with row rules), then a closing rule. The closing rule is either a single piece or a third rule drawn in the same
    pieces as the header. The pieces of the header-bottom rule are the columns.
    """
    width = caption[2] - caption[0]
    rules = [r for r in rules if x_overlap(r["x0"], r["x1"], caption[0], caption[2]) >= 0.5 * min(r["x1"] - r["x0"], width)]
    below = [r for r in rules if r["y"] > caption[3] and (next_caption_y is None or r["y"] < next_caption_y)]
    singles = [r for r in below if len(r["spans"]) == 1 and r["x1"] - r["x0"] >= CLOSING_WIDTH * width]
    multis = [r for r in below if len(r["spans"]) >= 2 and (not singles or r["y"] < singles[0]["y"])]
    reference = max((m["coverage"] for m in multis), default=0.0)
    full = [m for m in multis if m["coverage"] >= FULL_WIDTH * reference] if reference else []
    if len(full) < 2:
        return None, "fewer than two full-width header rules between the caption and the closing rule"

    closing = None
    if singles:
        top, bottom = full[0], full[-1]
        after = [r for r in singles if r["y"] > bottom["y"]]
        run = []
        for r in after:                      # row rules: a run of single rules as wide as the header
            if same_extent(r, bottom):
                run.append(r)
            else:
                break
        if len(run) >= 3:
            closing = after[len(run)] if len(after) > len(run) else run[-1]
        elif after:
            closing = after[0]
    elif len(full) >= 3 and full[-1]["y"] - full[-2]["y"] >= 30 and len(full[-1]["spans"]) == len(full[-2]["spans"]) \
            and same_extent(full[-1], full[-2]):
        top, bottom, closing = full[0], full[-2], full[-1]       # closing rule drawn in the header's own pieces
    if closing is None:
        return None, "no closing rule found below the header (the table may continue on the next page)"
    inside = [r for r in rules if caption[3] < r["y"] < closing["y"]]
    return TableLayout(top["y"], bottom["y"], closing["y"], sorted(bottom["spans"]), sorted(top["spans"]),
                       [r["y"] for r in inside if top["y"] < r["y"] < bottom["y"]]), None


def cluster_lines(words: list[dict]) -> list[list[dict]]:
    """Group words into text lines by vertical centre; the tolerance follows the font size so subscripts stay put."""
    if not words:
        return []
    heights = sorted(w["y1"] - w["y0"] for w in words)
    tol = max(1.5, 0.5 * heights[len(heights) // 2])
    lines: list[tuple[float, list[dict]]] = []
    for w in sorted(words, key=lambda w: (w["y0"] + w["y1"]) / 2):
        centre = (w["y0"] + w["y1"]) / 2
        if lines and abs(centre - lines[-1][0]) <= tol:
            members = lines[-1][1] + [w]
            lines[-1] = (sum((m["y0"] + m["y1"]) / 2 for m in members) / len(members), members)
        else:
            lines.append((centre, [w]))
    return [sorted(members, key=lambda w: w["x0"]) for _, members in lines]


def straddles_columns(line: list[dict], columns: list[tuple[float, float]]) -> bool:
    """True if any word overlaps two columns or sits in a gap: running text does not follow the column grid."""
    for w in line:
        hits = sum(1 for c in columns if min(w["x1"], c[1]) - max(w["x0"], c[0]) > 1.0)
        centre = (w["x0"] + w["x1"]) / 2
        in_a_column = any(c[0] <= centre <= c[1] for c in columns)
        if hits >= 2 or (not in_a_column and columns[0][0] <= centre <= columns[-1][1]):
            return True
    return False


def is_footnote_line(line: list[dict], columns: list[tuple[float, float]], gap_before: float | None,
                     spacing: float | None) -> bool:
    """Decide whether a trailing line under the table is a footnote and not a data row.

    A footnote (1) has three or more words and crosses the column grid, or (2) is a short single cluster that starts
    with a footnote marker ("aNot determined."), or (3) is a single cluster sitting well below the previous row.
    Dense numeric rows in narrow columns have small gaps too, so small gaps alone prove nothing.
    """
    if not line:
        return False
    one_cluster = all(b["x0"] - a["x1"] < SENTENCE_GAP for a, b in zip(line, line[1:]))
    if len(line) >= 3 and straddles_columns(line, columns):
        return True
    if one_cluster and FOOTNOTE_MARKER.match(line[0]["text"]):
        return True
    return one_cluster and gap_before is not None and spacing is not None and gap_before >= 1.5 * spacing


def join_words(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


def extract_grid(layout: TableLayout, words: list[dict], exclude: list[Box]) -> tuple[list[list[RawCell]], str | None]:
    """Build the cell grid (row 0 = header) from the words between the rules; return (grid, footnote text).

    Words inside `exclude` boxes (detected molecule drawings: their atom labels) are ignored. Body rows are text
    lines; trailing running-text lines are footnotes. A header cell that spans several columns on the top rule is
    copied to each column it covers, ahead of the text that sits above that column alone.
    """
    columns = layout.columns
    left, right = columns[0][0] - 5, columns[-1][1] + 5
    bounds = [(columns[i][1] + columns[i + 1][0]) / 2 for i in range(len(columns) - 1)]

    def column_of(xc: float) -> int:
        return next((i for i, b in enumerate(bounds) if xc < b), len(columns) - 1)

    usable = []
    for w in words:
        box = (w["x0"], w["y0"], w["x1"], w["y1"])
        xc, yc = (w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2
        if left <= xc <= right and layout.top_y <= yc <= layout.closing_y \
                and not any(overlap_fraction(box, e) >= 0.5 for e in exclude):
            usable.append(w)
    header_words = [w for w in usable if (w["y0"] + w["y1"]) / 2 < layout.header_bottom_y]
    body_words = [w for w in usable if (w["y0"] + w["y1"]) / 2 >= layout.header_bottom_y]

    group_limit = layout.inner_ys[0] if layout.inner_ys else None
    headings: list[list[dict]] = [[] for _ in columns]
    for line in cluster_lines(header_words):
        for w in line:
            xc, yc = (w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2
            targets = [column_of(xc)]
            if group_limit is not None and yc < group_limit:
                span = next((s for s in layout.group_spans if s[0] <= xc <= s[1]), None)
                if span:
                    targets = [i for i, c in enumerate(columns) if span[0] <= (c[0] + c[1]) / 2 <= span[1]] or targets
            for i in targets:
                headings[i].append(w)
    grid = [[RawCell(join_words(headings[i]), (c[0], layout.top_y, c[1], layout.header_bottom_y))
             for i, c in enumerate(columns)]]

    lines = cluster_lines(body_words)
    notes: list[list[dict]] = []
    centres = [sum((w["y0"] + w["y1"]) / 2 for w in line) / len(line) for line in lines]
    steps = sorted(b - a for a, b in zip(centres, centres[1:]))
    spacing = steps[len(steps) // 2] if steps else None            # typical distance between rows
    while lines and is_footnote_line(lines[-1], columns, centres[-1] - centres[-2] if len(centres) > 1 else None, spacing):
        notes.insert(0, lines.pop())
        centres.pop()
    for line in lines:
        y0, y1 = min(w["y0"] for w in line), max(w["y1"] for w in line)
        cells: list[list[dict]] = [[] for _ in columns]
        for w in line:
            cells[column_of((w["x0"] + w["x1"]) / 2)].append(w)
        grid.append([RawCell(join_words(cells[i]), (c[0], y0, c[1], y1)) for i, c in enumerate(columns)])
    note_text = " ".join(join_words(line) for line in notes) or None
    return grid, note_text


MIN_DRAWINGS = 3           # a table with no text layer needs this many detected drawings to be built from them


def rows_of_boxes(boxes: list[Box]) -> list[list[Box]]:
    """Group drawings into table rows by vertical centre (a row's drawings differ in height, so use centres)."""
    if not boxes:
        return []
    heights = sorted(b[3] - b[1] for b in boxes)
    tol = max(5.0, 0.6 * heights[len(heights) // 2])
    rows: list[tuple[float, list[Box]]] = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        centre = (b[1] + b[3]) / 2
        if rows and abs(centre - rows[-1][0]) <= tol:
            members = rows[-1][1] + [b]
            rows[-1] = (sum((m[1] + m[3]) / 2 for m in members) / len(members), members)
        else:
            rows.append((centre, [b]))
    return [members for _, members in rows]


def grid_from_drawings(layout: TableLayout, boxes: list[Box]) -> list[list[RawCell]]:
    """Body rows of a table whose text cannot be read: one row per group of drawings, one cell per column.

    A drawing belongs to the column its centre falls in; each cell's box grows to contain its drawings so they link
    to it. Cells carry no text. Which R-position a column holds is unknown here (its header is outlined too).
    """
    columns = layout.columns
    edges = [columns[0][0]] + [(columns[i][1] + columns[i + 1][0]) / 2 for i in range(len(columns) - 1)] + [columns[-1][1]]

    def column_of(box: Box) -> int:
        xc = (box[0] + box[2]) / 2
        return next((i for i in range(len(columns)) if xc < edges[i + 1]), len(columns) - 1)

    rows = []
    for members in rows_of_boxes(boxes):
        y0, y1 = min(b[1] for b in members), max(b[3] for b in members)
        cells = []
        for i in range(len(columns)):
            mine = [b for b in members if column_of(b) == i]
            x0 = min([edges[i]] + [b[0] for b in mine])
            x1 = max([edges[i + 1]] + [b[2] for b in mine])
            cells.append(RawCell("", (x0, y0, x1, y1)))
        rows.append(cells)
    return rows


def table_from_caption(caption: dict, rules: list[dict], words: list[dict], exclude: list[Box],
                       next_caption_y: float | None) -> RawTable:
    box = (caption["x0"], caption["y0"], caption["x1"], caption["y1"])
    text = " ".join(caption["text"].split())
    layout, reason = locate_table(box, rules, next_caption_y)
    if layout is None:
        return RawTable(bbox=box, grid=[], caption=text, block=box, reason=reason)
    grid, notes = extract_grid(layout, words, exclude)
    bbox = (layout.columns[0][0], layout.top_y, layout.columns[-1][1], layout.closing_y)
    block = (box[0], box[1], max(box[2], bbox[2]), layout.closing_y)
    reason = None
    if len(grid) < 2:
        header_has_text = any(c.text for c in grid[0])
        drawings = [b for b in exclude if overlap_fraction(b, bbox) >= 0.5 and (b[1] + b[3]) / 2 >= layout.header_bottom_y]
        if len(drawings) >= MIN_DRAWINGS:
            grid = grid[:1] + grid_from_drawings(layout, drawings)
            reason = (f"no text layer in the table; rows built from {len(drawings)} detected drawings only "
                      f"(labels and values need OCR)")
        elif not header_has_text:
            reason = "no text layer in the table's area (its contents are an image, outlined text or drawings)"
        else:
            reason = "no body text between the header rule and the closing rule"
    return RawTable(bbox=bbox, grid=grid, caption=text, notes=notes, block=block, reason=reason)


def captioned_tables(page, page_no: int, blocks: list[dict], regions: list[dict]) -> list[RawTable]:
    """One table per 'Table N.' caption on the page, built from the rules and words between caption and closing rule.

    Needs the molecule regions found so far on this page so atom labels of drawings are not read as cell text.
    """
    page_blocks = [b for b in blocks if b["page"] == page_no]
    captions = sorted((b for b in page_blocks if CAPTION_TABLE.match(b["text"])), key=lambda b: b["y0"])
    if not captions:
        return []
    rules = rule_groups(collect_rule_pieces(page))
    words = [{"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "text": w[4]} for w in page.get_text("words")]
    exclude = [(r["x0"], r["y0"], r["x1"], r["y1"]) for r in regions
               if r["page"] == page_no and r["gate"] in ("molecule", "uncertain")]
    all_captions = [b for b in page_blocks if CAPTION_ANY.match(b["text"])]
    return [table_from_caption(c, rules, words, exclude, next_caption_below(c, all_captions)) for c in captions]


# ---------------------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------------------
def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_regions(path: Path, regions: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REGION_FIELDS)
        writer.writeheader()
        writer.writerows(regions)


def count_by(items: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item[key]] = counts.get(item[key], 0) + 1
    return counts


def package_versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for package in ("pymupdf", "ultralytics", "torch", "numpy", "pillow"):
        try:
            out[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            out[package] = "not installed"
    return out


# ---------------------------------------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------------------------------------
def process_paper(pdf: Path, paper_id: str, out: Path, detector, settings: Settings) -> dict:
    """Render, detect, gate and find tables for one paper; write its files; return counts."""
    with pymupdf.open(pdf) as doc:
        if not doc.is_pdf or doc.needs_pass or len(doc) == 0:
            raise ValueError(f"paper {paper_id}: input must be a readable, nonempty, unencrypted PDF")
        page_count, block_count = render_document(doc, out, paper_id, settings.dpi)
        paper_dir = out / "papers" / paper_id
        pages = read_jsonl(paper_dir / "pages.jsonl")
        blocks = read_jsonl(paper_dir / "text.jsonl")
        regions: list[dict] = []
        tables: list[dict] = []
        for page in pages:
            page_no = page["page"]
            if detector is not None:
                with Image.open(out / page["image_path"]) as picture:
                    image = np.asarray(picture.convert("RGB"))
                for record, crop_px in make_regions(paper_id, page_no, page, detector(image), settings.conf,
                                                    settings.pad):
                    if crop_px is not None:
                        x0, y0, x1, y1 = crop_px
                        Image.fromarray(image[y0:y1, x0:x1]).save(out / record["crop_path"])
                    regions.append(record)
            if settings.table_strategy == "captions":
                raw_tables = captioned_tables(doc[page_no - 1], page_no, blocks, regions)
            else:
                raw_tables = raw_tables_from_page(doc[page_no - 1], settings.table_strategy,
                                                  settings.vertical_strategy, settings.horizontal_strategy)
            for index, raw in enumerate(raw_tables):
                tables.append(table_record(paper_id, page_no, index, raw, blocks, regions))
        write_regions(paper_dir / "regions.csv", regions)
        write_jsonl(paper_dir / "tables.jsonl", tables)
    return {"pages": page_count, "text_blocks": block_count, "regions": len(regions),
            "by_gate": count_by(regions, "gate"), "tables": len(tables), "tables_by_status": count_by(tables, "status")}


def run_frontend(papers: dict[str, Path], out: Path, settings: Settings, detector=None, dataset: str = "internal",
                 command: list[str] | None = None) -> dict:
    """Run the front end over `papers` ({paper_id: pdf}) into a NEW directory and write run.json.

    Failures are recorded in run.json and re-raised: an exception never becomes a successful empty run.
    """
    for paper_id in papers:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", paper_id):
            raise ValueError("paper_id must be a simple identifier, not a path")
    if not 0 <= settings.floor <= settings.conf <= 1:
        raise ValueError("need 0 <= floor <= conf <= 1")
    if not 72 <= settings.dpi <= 600:
        raise ValueError("dpi must be between 72 and 600")
    inputs = {pid: {"file": Path(pdf).name, "sha256": hashlib.sha256(Path(pdf).resolve(strict=True).read_bytes()).hexdigest()}
              for pid, pdf in papers.items()}
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=False)  # existing output directories are refused, as in smoke.py
    meta: dict = {
        "schema_version": "0.1", "task": "frontend", "dataset": dataset, "tool": "phase2-frontend",
        "paper_ids": list(papers), "inputs": inputs, "git_commit": git_revision(),
        "hardware": f"{platform.machine()} {platform.system()} {platform.release()}, {settings.device}",
        "versions": package_versions(),
        "settings": {"dpi": settings.dpi, "accept_conf": settings.conf, "detector_floor": settings.floor,
                     "pad_px": settings.pad, "device": settings.device, "table_strategy": settings.table_strategy,
                     "vertical_strategy": settings.vertical_strategy, "horizontal_strategy": settings.horizontal_strategy,
                     "skip_detection": settings.skip_detection, "min_side_px": MIN_SIDE_PX, "max_aspect": MAX_ASPECT},
        "command": command or ["python", "-m", "pipeline.frontend"], "status": "running", "stages": {},
        "notes": "Front-end stage only: reading, linking, assembly and export are not run, so there is no predictions.csv.",
    }
    try:
        if settings.skip_detection:
            detector = None
        elif detector is None:
            detector = MolDetV2Detector(settings.floor, settings.device)
            meta["versions"]["moldetv2_weights"] = "/".join(MolDetV2Detector.WEIGHTS)
        per_paper = {}
        for paper_id, pdf in papers.items():
            per_paper[paper_id] = process_paper(Path(pdf), paper_id, out, detector, settings)
            stats = per_paper[paper_id]
            print(f"paper {paper_id}: {stats['pages']} pages, {stats['regions']} regions {stats['by_gate']}, "
                  f"{stats['tables']} tables {stats['tables_by_status']}", flush=True)
        regions = sum(s["regions"] for s in per_paper.values())
        tables = sum(s["tables"] for s in per_paper.values())
        meta["stages"]["render_text"] = {"status": "complete", "pages": sum(s["pages"] for s in per_paper.values()),
                                         "text_blocks": sum(s["text_blocks"] for s in per_paper.values())}
        stage = {"status": "stub" if settings.skip_detection else "complete", "regions": regions, "tables": tables}
        if settings.skip_detection:
            stage["reason"] = "detection skipped (--skip-detection): tables only, so cells carry no box_id"
        meta["stages"]["detect_gate_tables"] = stage
        meta["papers"] = per_paper
        meta["status"] = "frontend_complete"
    except Exception as error:
        meta["status"] = "error"
        meta["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        meta["runtime_s"] = round(time.perf_counter() - started, 3)
        (out / "run.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------------------------------------
# Checking a run (use before sending files to the team)
# ---------------------------------------------------------------------------------------------------------
def _is_box(value, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    return isinstance(value, list) and len(value) == 4 and all(isinstance(v, (int, float)) for v in value)


def validate_run(run_dir: Path) -> list[str]:
    """Return a list of problems with a front-end run; an empty list means the files agree with the contract.

    Checks the fields INTERFACES.md requires, unique IDs, and that every reference (cell box_id, scaffold_box_id,
    evidence_block_ids) resolves within the same paper.
    """
    run_dir = Path(run_dir)
    problems: list[str] = []
    if not (run_dir / "run.json").is_file():
        problems.append("run.json is missing")
    papers_dir = run_dir / "papers"
    if not papers_dir.is_dir():
        return problems + ["papers/ is missing"]
    seen_boxes: set[str] = set()
    for paper_dir in sorted(p for p in papers_dir.iterdir() if p.is_dir()):
        pid = paper_dir.name
        missing = [n for n in ("pages.jsonl", "text.jsonl", "regions.csv", "tables.jsonl") if not (paper_dir / n).is_file()]
        if missing:
            problems.append(f"{pid}: missing {', '.join(missing)}")
            continue
        blocks = {b["block_id"]: b for b in read_jsonl(paper_dir / "text.jsonl")}
        with (paper_dir / "regions.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            lacking = [c for c in REGION_COLUMNS if c not in (reader.fieldnames or [])]
            region_rows = list(reader)
        if lacking:
            problems.append(f"{pid}: regions.csv lacks columns {', '.join(lacking)}")
        box_ids: set[str] = set()
        for row in region_rows:
            box_id = row.get("box_id", "")
            if box_id in seen_boxes:
                problems.append(f"{pid}: duplicate box_id {box_id}")
            seen_boxes.add(box_id)
            box_ids.add(box_id)
            if row.get("gate") not in VALID_GATES:
                problems.append(f"{pid}: {box_id} has gate {row.get('gate')!r}")
            if row.get("crop_path") and not (run_dir / row["crop_path"]).is_file():
                problems.append(f"{pid}: {box_id} crop file {row['crop_path']} is missing")
        table_ids: set[str] = set()
        for table in read_jsonl(paper_dir / "tables.jsonl"):
            tid = table.get("table_id", "?")
            absent = [k for k in TABLE_KEYS if k not in table]
            if absent:
                problems.append(f"{pid}: table {tid} lacks {', '.join(absent)}")
                continue
            if tid in table_ids:
                problems.append(f"{pid}: duplicate table_id {tid}")
            table_ids.add(tid)
            if table["paper_id"] != pid:
                problems.append(f"{pid}: table {tid} names paper {table['paper_id']}")
            if table["status"] not in VALID_STATUS:
                problems.append(f"{pid}: table {tid} has status {table['status']!r}")
            if not _is_box(table["bbox"]):
                problems.append(f"{pid}: table {tid} bbox is not four numbers")
            if table["scaffold_box_id"] is not None and table["scaffold_box_id"] not in box_ids:
                problems.append(f"{pid}: table {tid} scaffold_box_id {table['scaffold_box_id']} is not a region")
            column_ids = set()
            for column in table["columns"]:
                absent = [k for k in COLUMN_KEYS if k not in column]
                if absent:
                    problems.append(f"{pid}: table {tid} column lacks {', '.join(absent)}")
                else:
                    column_ids.add(column["column_id"])
            for row in table["rows"]:
                absent = [k for k in ROW_KEYS if k not in row]
                if absent:
                    problems.append(f"{pid}: table {tid} row lacks {', '.join(absent)}")
                    continue
                for cell in row["cells"]:
                    absent = [k for k in CELL_KEYS if k not in cell]
                    if absent:
                        problems.append(f"{pid}: table {tid} cell lacks {', '.join(absent)}")
                        continue
                    where = f"{pid}: table {tid} {cell['cell_id']}"
                    if cell["column_id"] not in column_ids:
                        problems.append(f"{where} names unknown column {cell['column_id']}")
                    if cell["box_id"] is not None and cell["box_id"] not in box_ids:
                        problems.append(f"{where} box_id {cell['box_id']} is not a region")
                    if not _is_box(cell["bbox"], nullable=True):
                        problems.append(f"{where} bbox is not four numbers or null")
                    for block_id in cell["evidence_block_ids"]:
                        if block_id not in blocks:
                            problems.append(f"{where} evidence block {block_id} does not exist")
                        elif blocks[block_id]["page"] != table["page"]:
                            problems.append(f"{where} evidence block {block_id} is on another page")
    return problems


# ---------------------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="new run directory, e.g. data/pipeline_runs/frontend-all")
    parser.add_argument("--check", type=Path, metavar="RUN_DIR", help="validate an existing run and exit")
    parser.add_argument("--pdf", type=Path, help="one PDF (needs --paper-id); default is the six internal papers")
    parser.add_argument("--paper-id", help="paper_id for --pdf")
    parser.add_argument("--pdf-dir", type=Path, default=REPO / "data" / "internal", help="folder holding <paper_id>.pdf")
    parser.add_argument("--papers", nargs="+", default=PAPERS, help="paper IDs inside --pdf-dir (default: all six)")
    parser.add_argument("--dpi", type=int, default=Settings.dpi)
    parser.add_argument("--conf", type=float, default=Settings.conf, help="accept threshold for gate=molecule")
    parser.add_argument("--floor", type=float, help="detector floor; boxes below --conf but above this become uncertain "
                                                    "(default: same as --conf, so no uncertain boxes)")
    parser.add_argument("--pad", type=int, default=Settings.pad, help="pixels around each box for the crop")
    parser.add_argument("--device", default=Settings.device)
    parser.add_argument("--table-strategy", choices=["lines", "lines_strict", "text", "captions"],
                        default=Settings.table_strategy,
                        help="captions: one table per 'Table N.' caption, from the drawn rules and words (journal tables)")
    parser.add_argument("--vertical-strategy", choices=["lines", "lines_strict", "text"],
                        help="column detection; with --horizontal-strategy it replaces --table-strategy")
    parser.add_argument("--horizontal-strategy", choices=["lines", "lines_strict", "text"], help="row detection")
    parser.add_argument("--skip-detection", action="store_true", help="tables only (no MolDetV2, no weights needed)")
    args = parser.parse_args(argv)

    if args.check:
        problems = validate_run(args.check)
        print("\n".join(problems) if problems else f"{args.check}: no problems found")
        return 1 if problems else 0
    if args.out is None:
        parser.error("--out is required (or use --check RUN_DIR)")
    if args.pdf:
        if not args.paper_id:
            parser.error("--pdf needs --paper-id")
        papers, dataset = {args.paper_id: args.pdf}, "custom"
    else:
        papers, dataset = {pid: args.pdf_dir / f"{pid}.pdf" for pid in args.papers}, "internal"
        missing = [str(p) for p in papers.values() if not p.is_file()]
        if missing:
            parser.error("PDF not found: " + ", ".join(missing) + " (see data/README.md for the internal papers)")
    settings = Settings(dpi=args.dpi, conf=args.conf, floor=args.floor, pad=args.pad, device=args.device,
                        table_strategy=args.table_strategy, vertical_strategy=args.vertical_strategy,
                        horizontal_strategy=args.horizontal_strategy, skip_detection=args.skip_detection)
    run_frontend(papers, args.out, settings, dataset=dataset, command=["python", "-m", "pipeline.frontend", *sys.argv[1:]])
    problems = validate_run(args.out)
    if problems:
        print("PROBLEMS:\n" + "\n".join(problems))
        return 1
    print(f"Wrote {args.out}; the files agree with INTERFACES.md (checked references and required fields).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
