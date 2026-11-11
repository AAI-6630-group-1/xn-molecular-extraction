"""End-to-end front-end tests on small synthetic PDFs (need PyMuPDF; the detector is a fake, so no weights).

The first test draws a ruled 3x3 table with one drawing in an empty cell. The rotated-page test checks the
contract's rule that coordinates stay unrotated: if PyMuPDF's find_tables returns rotated coordinates, the
table's cell text would no longer line up with the text blocks and the front end abstains, which fails the test.

AI disclosure: Claude (Anthropic) drafted these tests for Peter Adranly, who ran them on his Mac; read any
failure before changing the front end.
"""
import json
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline import frontend
from pipeline.frontend import Detection, Settings, run_frontend

XS = [40, 120, 200, 280]
YS = [60, 100, 140, 180]
TEXTS = [["Cpd", "R1", "R2"], ["12a", "Me", "H"], ["12b", "Et", ""]]     # the last cell holds a drawing


class FakeDetector:
    """Returns fixed boxes in pixels of the rendered page (144 dpi, so 2 px per point)."""

    def __init__(self, boxes):
        self.boxes = boxes

    def __call__(self, image):
        return [Detection(*b) for b in self.boxes]


def draw_table_pdf(path, rotation=0):
    with pymupdf.open() as doc:
        page = doc.new_page(width=320, height=400)
        for x in XS:
            page.draw_line((x, YS[0]), (x, YS[-1]), width=0.8)
        for y in YS:
            page.draw_line((XS[0], y), (XS[-1], y), width=0.8)
        for i, row in enumerate(TEXTS):
            for j, text in enumerate(row):
                if text:
                    page.insert_text((XS[j] + 6, YS[i] + 24), text, fontsize=11)
        page.insert_text((40, 30), "Table 1. Example R-group table", fontsize=10)
        if rotation:
            page.set_rotation(rotation)
        doc.save(path)
    return path


@pytest.fixture
def pdf(tmp_path):
    return draw_table_pdf(tmp_path / "table.pdf")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def test_front_end_writes_the_contract_files_and_a_linked_table(pdf, tmp_path):
    out = tmp_path / "run"
    detector = FakeDetector([(410, 290, 550, 350, 0.9),      # the drawing inside the empty cell (200-280, 140-180 pt)
                             (80, 20, 300, 100, 0.8)])       # a molecule above the table
    meta = run_frontend({"7": pdf}, out, Settings(dpi=144), detector=detector, dataset="test")
    paper = out / "papers" / "7"
    for name in ("pages.jsonl", "text.jsonl", "regions.csv", "tables.jsonl"):
        assert (paper / name).is_file()
    assert (paper / "crops" / "7-p1-0.png").is_file() and (paper / "crops" / "7-p1-1.png").is_file()
    assert meta["status"] == "frontend_complete" and meta["stages"]["detect_gate_tables"]["status"] == "complete"

    tables = read_jsonl(paper / "tables.jsonl")
    assert len(tables) == 1
    table = tables[0]
    assert table["status"] == "ok", table["reason"]
    assert [c["heading"] for c in table["columns"]] == ["Cpd", "R1", "R2"]
    assert [r["label"] for r in table["rows"]] == ["12a", "12b"]
    assert table["rows"][0]["cells"][1]["text"] == "Me"
    drawing_cell = table["rows"][1]["cells"][2]
    assert drawing_cell["box_id"] == "7-p1-0" and drawing_cell["text"] == ""
    assert table["scaffold_box_id"] == "7-p1-1"
    assert frontend.validate_run(out) == []


def test_front_end_without_detection_still_builds_tables_and_says_so(pdf, tmp_path):
    out = tmp_path / "run"
    meta = run_frontend({"7": pdf}, out, Settings(dpi=144, skip_detection=True), dataset="test")
    assert meta["stages"]["detect_gate_tables"]["status"] == "stub"
    table = read_jsonl(out / "papers/7/tables.jsonl")[0]
    assert table["status"] == "ok" and table["scaffold_box_id"] is None
    assert all(c["box_id"] is None for r in table["rows"] for c in r["cells"])
    assert list((out / "papers/7/crops").glob("*.png")) == []          # no detector, no crops


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_pages_keep_table_cells_aligned_with_the_text_blocks(tmp_path, rotation):
    pdf = draw_table_pdf(tmp_path / "rotated.pdf", rotation=rotation)
    out = tmp_path / "run"
    run_frontend({"7": pdf}, out, Settings(dpi=144, skip_detection=True), dataset="test")
    tables = read_jsonl(out / "papers/7/tables.jsonl")
    assert len(tables) == 1 and tables[0]["status"] == "ok", tables[0]["reason"] if tables else "no table found"
    assert tables[0]["rows"][0]["cells"][1]["text"] == "Me"
    assert frontend.validate_run(out) == []


def test_existing_output_directory_is_refused(pdf, tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    (out / "run.json").write_text("original")
    with pytest.raises(FileExistsError):
        run_frontend({"7": pdf}, out, Settings(skip_detection=True))
    assert (out / "run.json").read_text() == "original"


def test_bad_paper_id_does_not_escape_the_output_directory(pdf, tmp_path):
    with pytest.raises(ValueError, match="simple identifier"):
        run_frontend({"../outside": pdf}, tmp_path / "run", Settings(skip_detection=True))


def test_a_failure_is_recorded_in_run_json_and_raised(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    out = tmp_path / "run"
    with pytest.raises(Exception):
        run_frontend({"7": bad}, out, Settings(skip_detection=True))
    assert json.loads((out / "run.json").read_text())["status"] == "error"


def test_command_line_runs_checks_and_returns_zero(pdf, tmp_path):
    out = tmp_path / "run"
    code = frontend.main(["--pdf", str(pdf), "--paper-id", "7", "--out", str(out), "--dpi", "144", "--skip-detection"])
    assert code == 0
    assert frontend.main(["--check", str(out)]) == 0


# ---------------------------------------------------------------------------------------------------------
# Caption-anchored tables: drawn the way the journal does it (header rules in pieces, no row lines, a footnote
# and one closing rule). Added after the first real-paper runs.
# ---------------------------------------------------------------------------------------------------------
JOURNAL_COLS = [(40, 110), (114, 184), (188, 258), (262, 332)]


def draw_journal_table(page, top, caption, header, rows, footnote, cols=JOURNAL_COLS):
    """Caption 30 pt above the top rule; header rules in one piece per column; rows without lines; footnote; closing rule."""
    page.insert_text((40, top - 30), caption, fontsize=10)
    for x0, x1 in cols:
        page.draw_line((x0, top), (x1, top), width=0.8)
        page.draw_line((x0, top + 25), (x1, top + 25), width=0.8)
    for (x0, _), text in zip(cols, header):
        page.insert_text((x0 + 4, top + 15), text, fontsize=9)
    for r, row in enumerate(rows):
        for (x0, _), text in zip(cols, row):
            page.insert_text((x0 + 4, top + 40 + 14 * r), text, fontsize=9)
    foot_y = top + 40 + 14 * len(rows) + 6
    page.insert_text((40, foot_y), footnote, fontsize=8)
    closing = foot_y + 8
    page.draw_line((cols[0][0], closing), (cols[-1][1], closing), width=0.5)
    return closing


ROWS = [["12a", "Me", "H", "10"], ["12b", "Et", "OMe", "25"], ["12c", "Pr", "F", "N.D."]]
FOOTNOTE = "aN.D. = not determined at the highest concentration tested."


def journal_pdf(path, rotation=0, second_table=False, ruled=True):
    with pymupdf.open() as doc:
        page = doc.new_page(width=400, height=500)
        if ruled:
            closing = draw_journal_table(page, 70, "Table 1. Example journal table", ["Cpd", "R1", "R2", "IC50"], ROWS, FOOTNOTE)
        else:
            page.insert_text((40, 40), "Table 1. A table with no rules", fontsize=10)
            page.insert_text((40, 80), "Cpd R1 R2 IC50", fontsize=9)
            closing = 100
        if second_table:
            draw_journal_table(page, closing + 60, "Table 2. A second table", ["Cmpd", "A", "B"], ROWS[:2], "bNone.",
                               cols=JOURNAL_COLS[:3])
        if rotation:
            page.set_rotation(rotation)
        doc.save(path)
    return path


def captions_settings(**kwargs):
    return Settings(dpi=144, table_strategy="captions", **kwargs)


def test_caption_method_builds_a_clean_grid_footnote_and_scaffold_link(tmp_path):
    pdf = journal_pdf(tmp_path / "journal.pdf")
    out = tmp_path / "run"
    detector = FakeDetector([(100, 90, 300, 135, 0.9)])       # a drawing between the caption and the top rule
    run_frontend({"7": pdf}, out, captions_settings(), detector=detector, dataset="test")
    (table,) = read_jsonl(out / "papers/7/tables.jsonl")
    assert table["status"] == "ok", table["reason"]
    assert table["caption"].startswith("Table 1.") and table["notes"].startswith("aN.D.")
    assert [c["heading"] for c in table["columns"]] == ["Cpd", "R1", "R2", "IC50"]
    assert [r["label"] for r in table["rows"]] == ["12a", "12b", "12c"]
    assert [c["text"] for c in table["rows"][1]["cells"]] == ["12b", "Et", "OMe", "25"]
    assert table["scaffold_box_id"] == "7-p1-0"
    assert frontend.validate_run(out) == []


def test_caption_method_separates_two_tables_on_one_page(tmp_path):
    pdf = journal_pdf(tmp_path / "stacked.pdf", second_table=True)
    out = tmp_path / "run"
    run_frontend({"7": pdf}, out, captions_settings(skip_detection=True), dataset="test")
    first, second = read_jsonl(out / "papers/7/tables.jsonl")
    assert first["status"] == second["status"] == "ok", (first["reason"], second["reason"])
    assert first["caption"].startswith("Table 1.") and second["caption"].startswith("Table 2.")
    assert [r["label"] for r in first["rows"]] == ["12a", "12b", "12c"]
    assert [r["label"] for r in second["rows"]] == ["12a", "12b"]
    assert [c["heading"] for c in second["columns"]] == ["Cmpd", "A", "B"]
    assert first["bbox"][3] < second["bbox"][1]                 # the tables do not overlap


def test_caption_method_keeps_a_table_it_cannot_build_as_an_abstain_record(tmp_path):
    pdf = journal_pdf(tmp_path / "unruled.pdf", ruled=False)
    out = tmp_path / "run"
    run_frontend({"7": pdf}, out, captions_settings(skip_detection=True), dataset="test")
    (table,) = read_jsonl(out / "papers/7/tables.jsonl")
    assert table["status"] == "abstain" and "closing rule" in table["reason"]
    assert table["caption"].startswith("Table 1.") and table["rows"] == []
    assert frontend.validate_run(out) == []


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_caption_method_on_rotated_pages(tmp_path, rotation):
    """If PyMuPDF reports drawings in rotated coordinates, the rules will not line up and this fails: read why."""
    pdf = journal_pdf(tmp_path / "rotated.pdf", rotation=rotation)
    out = tmp_path / "run"
    run_frontend({"7": pdf}, out, captions_settings(skip_detection=True), dataset="test")
    (table,) = read_jsonl(out / "papers/7/tables.jsonl")
    assert table["status"] == "ok", table["reason"]
    assert [r["label"] for r in table["rows"]] == ["12a", "12b", "12c"]


def test_command_line_accepts_the_caption_strategy(tmp_path):
    pdf = journal_pdf(tmp_path / "cli.pdf")
    out = tmp_path / "run"
    code = frontend.main(["--pdf", str(pdf), "--paper-id", "7", "--out", str(out), "--dpi", "144",
                          "--skip-detection", "--table-strategy", "captions"])
    assert code == 0
    assert json.loads((out / "run.json").read_text())["settings"]["table_strategy"] == "captions"
