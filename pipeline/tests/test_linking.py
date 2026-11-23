"""Check label linking on the hand-made fixture paper."""
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.linking import as_label, link_paper, read_jsonl, write_jsonl

FIXTURE = Path(__file__).parent / "fixtures" / "papers" / "fixture"


@pytest.fixture
def paper(tmp_path):
    """A copy of the fixture paper folder that a test may edit."""
    folder = tmp_path / "papers" / "fixture"
    shutil.copytree(FIXTURE, folder)
    return folder


def drawing_links(links):
    return {link["box_id"]: link for link in links if link["table_id"] is None}


def row_links(links):
    return [link for link in links if link["table_id"] is not None]


def set_scaffold(paper, box_id):
    tables = read_jsonl(paper / "tables.jsonl")
    tables[0]["scaffold_box_id"] = box_id
    write_jsonl(paper / "tables.jsonl", tables)


def test_fixture_gives_the_expected_links(paper):
    assert link_paper(paper) == read_jsonl(paper / "expected_links.jsonl")


def test_complete_drawing_takes_the_label_below(paper):
    link = drawing_links(link_paper(paper))["fixture-p1-0"]
    assert (link["label"], link["status"]) == ("12a", "ok")
    assert link["evidence_block_ids"] == ["fixture-p1-t0"]


def test_table_rows_link_to_the_scaffold_above(paper):
    rows = [link for link in row_links(link_paper(paper)) if link["box_id"] == "fixture-p1-1"]
    assert [link["label"] for link in rows] == ["13a", "13b"]
    assert {link["status"] for link in rows} == {"ok"}


def test_drawn_substituent_links_to_its_row(paper):
    [link] = [link for link in row_links(link_paper(paper)) if link["box_id"] == "fixture-p1-4"]
    assert (link["label"], link["row_id"]) == ("13b", "fixture-p1-tab0-r1")


def test_non_molecule_region_gets_no_link(paper):
    assert "fixture-p1-2" not in {link["box_id"] for link in link_paper(paper)}


def test_equally_close_labels_abstain(paper):
    link = drawing_links(link_paper(paper))["fixture-p1-3"]
    assert (link["label"], link["status"]) == (None, "abstain")
    assert link["evidence_block_ids"] == ["fixture-p1-t6", "fixture-p1-t7"]


def test_drawing_with_no_label_abstains(paper):
    link = drawing_links(link_paper(paper))["fixture-p2-0"]
    assert (link["status"], link["reason"]) == ("abstain", "no label near the drawing")


def test_label_goes_to_the_closer_drawing(paper):
    # A second drawing under the first one also reaches label 12a, but from farther away.
    with (paper / "regions.csv").open("a", encoding="utf-8") as stream:
        stream.write("fixture,1,fixture-p1-5,110,196,190,226,crops/fixture-p1-5.png,molecule,molecule,0.9,\n")
    links = drawing_links(link_paper(paper))
    assert links["fixture-p1-0"]["label"] == "12a"
    assert links["fixture-p1-5"]["status"] == "abstain"
    assert links["fixture-p1-5"]["reason"] == "label 12a is closer to fixture-p1-0"


def test_front_end_scaffold_is_kept(paper):
    set_scaffold(paper, "fixture-p1-3")
    rows = row_links(link_paper(paper))
    assert {link["box_id"] for link in rows if link["box_id"] != "fixture-p1-4"} == {"fixture-p1-3"}
    assert rows[0]["reason"] == "scaffold given by the front end"


def test_unknown_scaffold_is_an_error(paper):
    set_scaffold(paper, "fixture-p9-0")
    rows = [link for link in row_links(link_paper(paper)) if link["box_id"] != "fixture-p1-4"]
    assert {link["status"] for link in rows} == {"error"}
    assert {link["box_id"] for link in rows} == {None}


def test_missing_input_file_is_an_error(paper):
    (paper / "readings.csv").unlink()
    with pytest.raises(FileNotFoundError):
        link_paper(paper)


@pytest.mark.parametrize("text, label", [
    ("12a\n", "12a"), ("7", "7"), ("NR-7h", "NR-7h"), ("(14b)", "14b"), ("S3", "S3"),
    ("Figure 2", None), ("1 2 3", None), ("12a-12f, 13", None), ("R", None), ("Me", None),
    ("MKK4", None), ("NTRK1", None), ("Glu179", None), ("NH2", None), ("A4", "A4"), ("B9", "B9"), ("R2", None),
])
def test_label_pattern(text, label):
    assert as_label(text) == label


def add_activity_table(paper, labels):
    """Append an IC50 table (no R column) whose rows name the given compounds."""
    rows = [{"row_id": f"fixture-p2-tab0-r{n}", "label": label,
             "cells": [{"cell_id": f"fixture-p2-tab0-r{n}c0", "column_id": "c0", "text": label,
                        "box_id": None, "bbox": [50, 300 + 10 * n, 90, 308 + 10 * n],
                        "evidence_block_ids": []}]}
            for n, label in enumerate(labels)]
    tables = read_jsonl(paper / "tables.jsonl")
    tables.append({"paper_id": "fixture", "page": 2, "table_id": "fixture-p2-tab0",
                   "bbox": [50, 290, 300, 400], "scaffold_box_id": None,
                   "columns": [{"column_id": "c0", "heading": "Compound"},
                               {"column_id": "c1", "heading": "IC50 (nM)"}],
                   "rows": rows, "status": "ok", "reason": None})
    write_jsonl(paper / "tables.jsonl", tables)


def test_activity_row_links_to_the_drawing_with_its_label(paper):
    add_activity_table(paper, ["12a", "99", "BLK"])
    rows = {link["label"]: link for link in row_links(link_paper(paper))
            if link["table_id"] == "fixture-p2-tab0"}
    assert (rows["12a"]["box_id"], rows["12a"]["status"]) == ("fixture-p1-0", "ok")
    assert (rows["99"]["status"], rows["99"]["box_id"]) == ("abstain", None)
    assert rows["BLK"]["reason"] == "row has no compound label"
