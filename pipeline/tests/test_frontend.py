"""Guard the front end's coordinates, gate, table records and reference checks (no PDF or model needed).

AI disclosure: Claude (Anthropic) drafted these tests for Peter Adranly; run them before opening a PR.
"""
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline import frontend
from pipeline.frontend import Detection, RawCell, RawTable
from pipeline.smoke import REGION_COLUMNS, write_jsonl

XS = [40, 120, 200, 280]
YS = [60, 100, 140, 180]


def cell_box(i, j):
    return (XS[j], YS[i], XS[j + 1], YS[i + 1])


def make_table(texts):
    """A 3x3 grid; `texts` is a list of rows of strings ('' = empty cell)."""
    return RawTable(bbox=(XS[0], YS[0], XS[-1], YS[-1]),
                    grid=[[RawCell(t, cell_box(i, j)) for j, t in enumerate(row)] for i, row in enumerate(texts)])


def blocks_for(texts, page=1, paper="7"):
    blocks = []
    for i, row in enumerate(texts):
        for j, text in enumerate(row):
            if text:
                x0, y0, x1, y1 = cell_box(i, j)
                blocks.append({"paper_id": paper, "page": page, "block_id": f"{paper}-p{page}-t{len(blocks)}",
                               "x0": x0 + 4, "y0": y0 + 8, "x1": x1 - 4, "y1": y1 - 8, "text": text,
                               "source": "pdf_text"})
    return blocks


def region(box_id, box, gate="molecule", page=1):
    return {"paper_id": "7", "page": page, "box_id": box_id, "x0": box[0], "y0": box[1], "x1": box[2], "y1": box[3],
            "gate": gate}


TEXTS = [["Cpd", "R1", "R2"], ["12a", "Me", "H"], ["12b", "Et", ""]]


def test_pixel_box_to_pdf_uses_all_four_corners_for_a_rotated_page():
    matrix = [0, 1, -1, 0, 100, 0]            # x' = 100 - y, y' = x
    assert frontend.pixel_box_to_pdf((10, 20, 30, 50), matrix) == (50, 10, 80, 30)


class FakeTable:
    """Mimics the parts of a PyMuPDF table that raw_tables_from_page reads."""

    def __init__(self, bbox, cell_rows, text_rows):
        self.bbox = bbox
        self.rows = [SimpleNamespace(cells=row) for row in cell_rows]
        self._text = text_rows

    def extract(self):
        return self._text


def fake_page(tables, derotation):
    seen = {}

    def find_tables(**options):
        seen.update(options)
        return SimpleNamespace(tables=tables)

    return SimpleNamespace(derotation_matrix=derotation, find_tables=find_tables, seen=seen)


def test_table_boxes_from_a_rotated_page_are_mapped_back_to_unrotated_coordinates():
    # A 320x400 page shown rotated 90 degrees: the table at (40,60,280,180) is reported at (220,40,340,280).
    derotate = [0, -1, 1, 0, 0, 400]                     # x = y', y = 400 - x'
    rotated_cell = (220, 40, 260, 120)                   # displayed position of the unrotated cell (40,140,120,180)
    table = FakeTable((220, 40, 340, 280), [[rotated_cell, None]], [["Me", None]])
    (raw,) = frontend.raw_tables_from_page(fake_page([table], derotate))
    assert raw.bbox == (40, 60, 280, 180)
    assert raw.grid[0][0].bbox == (40, 140, 120, 180) and raw.grid[0][0].text == "Me"
    assert raw.grid[0][1].bbox is None and raw.grid[0][1].text == ""


def test_table_strategies_are_passed_through_to_pymupdf():
    identity = [1, 0, 0, 1, 0, 0]
    page = fake_page([], identity)
    frontend.raw_tables_from_page(page, "text")
    assert page.seen == {"strategy": "text"}
    page = fake_page([], identity)
    frontend.raw_tables_from_page(page, "lines", vertical="text", horizontal="lines")
    assert page.seen == {"vertical_strategy": "text", "horizontal_strategy": "lines"}
    page = fake_page([], identity)
    frontend.raw_tables_from_page(page, "lines", vertical="text")          # the other one defaults to lines
    assert page.seen == {"vertical_strategy": "text", "horizontal_strategy": "lines"}


def test_a_block_spanning_several_cells_is_evidence_for_each_of_them():
    row_block = {"paper_id": "7", "page": 1, "block_id": "7-p1-t0", "x0": 40, "y0": 100, "x1": 280, "y1": 140,
                 "text": "12a Me H", "source": "pdf_text"}                     # one block holding the whole row
    header = [{"paper_id": "7", "page": 1, "block_id": f"7-p1-t{i + 1}", "x0": XS[i] + 4, "y0": 68, "x1": XS[i + 1] - 4,
               "y1": 92, "text": h, "source": "pdf_text"} for i, h in enumerate(["Cpd", "R1", "R2"])]
    table = make_table([["Cpd", "R1", "R2"], ["12a", "Me", "H"]])
    record = frontend.table_record("7", 1, 0, table, header + [row_block], [])
    assert record["status"] == "ok"
    assert [c["evidence_block_ids"] for c in record["rows"][0]["cells"]] == [["7-p1-t0"]] * 3


def test_a_distant_block_is_not_evidence_for_a_cell():
    far = {"paper_id": "7", "page": 1, "block_id": "7-p1-t0", "x0": 40, "y0": 300, "x1": 280, "y1": 340,
           "text": "elsewhere", "source": "pdf_text"}
    assert frontend.blocks_in_cell([far], (120, 100, 200, 140)) == []


def test_table_boxes_on_an_unrotated_page_are_unchanged():
    identity = [1, 0, 0, 1, 0, 0]
    table = FakeTable((40, 60, 280, 180), [[(40, 60, 120, 100)]], [["Cpd"]])
    (raw,) = frontend.raw_tables_from_page(fake_page([table], identity))
    assert raw.bbox == (40, 60, 280, 180) and raw.grid[0][0].bbox == (40, 60, 120, 100)


def test_pixel_box_to_pdf_scales_without_rotation():
    assert frontend.pixel_box_to_pdf((100, 200, 300, 400), [0.5, 0, 0, 0.5, 0, 0]) == (50, 100, 150, 200)


def test_gate_thresholds_and_reasons():
    gate = frontend.gate_detection
    assert gate(Detection(0, 0, 100, 100, 0.9), 0.5) == ("molecule", None)
    assert gate(Detection(0, 0, 100, 100, 0.5), 0.5) == ("molecule", None)
    assert gate(Detection(0, 0, 100, 100, 0.3), 0.5)[0] == "uncertain"
    assert gate(Detection(0, 0, 10, 10, 0.99), 0.5)[0] == "non_molecule"        # too small
    assert gate(Detection(0, 0, 400, 20, 0.99), 0.5)[0] == "non_molecule"       # a rule or border
    assert gate(Detection(5, 5, 5, 50, 0.99), 0.5) == ("non_molecule", "empty box")


def test_regions_get_stable_ids_gates_and_padded_crop_boxes():
    page = {"pixel_to_pdf": [0.5, 0, 0, 0.5, 0, 0], "width_px": 600, "height_px": 800}
    detections = [Detection(100, 200, 300, 400, 0.9), Detection(50, 50, 250, 150, 0.3), Detection(10, 10, 20, 20, 0.9)]
    made = frontend.make_regions("7", 1, page, detections, accept=0.5, pad=10)
    records = [r for r, _ in made]
    assert [r["box_id"] for r in records] == ["7-p1-0", "7-p1-1", "7-p1-2"]
    assert [r["gate"] for r in records] == ["molecule", "uncertain", "non_molecule"]
    first = records[0]
    assert (first["x0"], first["y0"], first["x1"], first["y1"]) == (50, 100, 150, 200)
    assert (first["crop_x0"], first["crop_y0"], first["crop_x1"], first["crop_y1"]) == (45, 95, 155, 205)
    assert made[0][1] == (90, 190, 310, 410)
    assert first["crop_path"] == "papers/7/crops/7-p1-0.png" and first["role"] == "unknown"
    assert records[2]["crop_path"] == "" and made[2][1] is None and records[2]["reason"]   # kept, with a reason


def test_crop_box_is_clamped_to_the_page_image():
    page = {"pixel_to_pdf": [1, 0, 0, 1, 0, 0], "width_px": 200, "height_px": 200}
    _, crop = frontend.make_regions("7", 1, page, [Detection(2, 3, 195, 198, 0.9)], 0.5, pad=10)[0]
    assert crop == (0, 0, 200, 200)


def test_table_record_keeps_every_field_and_links_text_and_drawings():
    regions = [region("7-p1-0", (205, 145, 275, 175)),             # a drawing inside the empty cell r2c2
               region("7-p1-1", (40, 10, 150, 50)),                # a molecule above the table: the scaffold
               region("7-p1-2", (40, 300, 100, 340))]              # a farther molecule
    record = frontend.table_record("7", 1, 0, make_table(TEXTS), blocks_for(TEXTS), regions)
    assert [r["row_id"] for r in record["rows"]] == ["7-p1-tab0-r0", "7-p1-tab0-r1"]           # table-prefixed, from 0
    assert record["rows"][1]["cells"][2]["cell_id"] == "7-p1-tab0-r1c2"
    assert set(record) == set(frontend.TABLE_KEYS) | set(frontend.TABLE_EXTRA_KEYS)
    assert record["caption"] is None and record["notes"] is None
    assert record["table_id"] == "7-p1-tab0" and record["status"] == "ok" and record["reason"] is None
    assert record["scaffold_box_id"] == "7-p1-1"
    assert [c["heading"] for c in record["columns"]] == ["Cpd", "R1", "R2"]
    assert [r["label"] for r in record["rows"]] == ["12a", "12b"]
    row2 = record["rows"][1]
    assert set(row2) == set(frontend.ROW_KEYS)
    assert all(set(c) == set(frontend.CELL_KEYS) for r in record["rows"] for c in r["cells"])
    drawing_cell = row2["cells"][2]
    assert drawing_cell["text"] == "" and drawing_cell["box_id"] == "7-p1-0" and drawing_cell["evidence_block_ids"] == []
    text_cell = record["rows"][0]["cells"][1]
    assert text_cell["text"] == "Me" and text_cell["box_id"] is None and len(text_cell["evidence_block_ids"]) == 1
    assert text_cell["bbox"] == [120, 100, 200, 140]
    json.dumps(record)                                              # serializable


def test_scaffold_is_null_when_two_molecules_are_equally_near_or_none_is_close():
    table = make_table(TEXTS)
    equal = [region("a", (40, 10, 100, 50)), region("b", (220, 10, 280, 50))]
    assert frontend.table_record("7", 1, 0, table, blocks_for(TEXTS), equal)["scaffold_box_id"] is None
    far = [region("a", (40, 600, 100, 640))]
    assert frontend.table_record("7", 1, 0, table, blocks_for(TEXTS), far)["scaffold_box_id"] is None
    uncertain_only = [region("a", (40, 10, 100, 50), gate="uncertain")]
    assert frontend.table_record("7", 1, 0, table, blocks_for(TEXTS), uncertain_only)["scaffold_box_id"] is None


def test_table_abstains_with_a_reason_instead_of_guessing():
    tiny = make_table([["a", "b"]])
    assert frontend.table_record("7", 1, 0, tiny, [], [])["status"] == "abstain"
    empty = make_table([["", "", ""], ["", "", ""], ["", "", ""]])
    assert "no text" in frontend.table_record("7", 1, 0, empty, [], [])["reason"]
    mismatched = frontend.table_record("7", 1, 0, make_table(TEXTS), [], [])        # text but no text blocks
    assert mismatched["status"] == "abstain" and "coordinates" in mismatched["reason"]


def test_merged_cell_without_geometry_keeps_null_fields():
    table = make_table(TEXTS)
    table.grid[1][1] = RawCell("Me", None)
    record = frontend.table_record("7", 1, 0, table, blocks_for(TEXTS), [])
    cell = record["rows"][0]["cells"][1]
    assert cell["bbox"] is None and cell["box_id"] is None and cell["evidence_block_ids"] == []


def build_run(tmp_path, tables, box_ids=("7-p1-0",)):
    """A minimal run folder: one paper, one text block, the given regions and tables."""
    run = tmp_path / "run"
    paper = run / "papers" / "7"
    (paper / "crops").mkdir(parents=True)
    (run / "run.json").write_text("{}")
    write_jsonl(paper / "pages.jsonl", [{"paper_id": "7", "page": 1}])
    write_jsonl(paper / "text.jsonl", [{"paper_id": "7", "page": 1, "block_id": "7-p1-t0", "x0": 0, "y0": 0,
                                        "x1": 1, "y1": 1, "text": "x", "source": "pdf_text"}])
    rows = [{**{c: "" for c in frontend.REGION_FIELDS}, "paper_id": "7", "page": 1, "box_id": b, "gate": "molecule"}
            for b in box_ids]
    frontend.write_regions(paper / "regions.csv", rows)
    write_jsonl(paper / "tables.jsonl", tables)
    return run


def good_table():
    return {"paper_id": "7", "page": 1, "table_id": "7-p1-tab0", "bbox": [0, 0, 10, 10], "scaffold_box_id": "7-p1-0",
            "columns": [{"column_id": "c0", "heading": None}],
            "rows": [{"row_id": "r1", "label": None, "cells": [
                {"cell_id": "r1c0", "column_id": "c0", "text": "x", "box_id": "7-p1-0", "bbox": None,
                 "evidence_block_ids": ["7-p1-t0"]}]}],
            "status": "ok", "reason": None}


def test_validate_run_accepts_a_consistent_run(tmp_path):
    assert frontend.validate_run(build_run(tmp_path, [good_table()])) == []


def test_validate_run_flags_a_table_missing_a_required_field(tmp_path):
    bad = good_table()
    del bad["reason"]
    assert "lacks reason" in "\n".join(frontend.validate_run(build_run(tmp_path, [bad])))


def test_validate_run_flags_each_dangling_reference(tmp_path):
    bad = good_table()
    bad["scaffold_box_id"] = "7-p1-99"
    bad["rows"][0]["cells"][0]["box_id"] = "7-p1-98"
    bad["rows"][0]["cells"][0]["evidence_block_ids"] = ["7-p1-t9"]
    problems = "\n".join(frontend.validate_run(build_run(tmp_path, [bad])))
    assert "7-p1-99" in problems and "7-p1-98" in problems and "7-p1-t9" in problems


def test_validate_run_flags_missing_files_duplicates_and_bad_status(tmp_path):
    run = build_run(tmp_path, [good_table(), good_table()], box_ids=("7-p1-0", "7-p1-0"))
    (run / "papers" / "7" / "tables.jsonl").write_text(
        "\n".join(json.dumps({**good_table(), "status": "maybe"}) for _ in range(2)) + "\n")
    problems = "\n".join(frontend.validate_run(run))
    assert "duplicate box_id" in problems and "duplicate table_id" in problems and "status 'maybe'" in problems
    (run / "papers" / "7" / "regions.csv").unlink()
    assert "missing regions.csv" in "\n".join(frontend.validate_run(run))


def test_regions_csv_keeps_the_contract_columns_first(tmp_path):
    path = tmp_path / "regions.csv"
    frontend.write_regions(path, [])
    with path.open(newline="") as stream:
        header = next(csv.reader(stream))
    assert header[:len(REGION_COLUMNS)] == REGION_COLUMNS
    assert header[len(REGION_COLUMNS):] == frontend.CROP_COLUMNS
