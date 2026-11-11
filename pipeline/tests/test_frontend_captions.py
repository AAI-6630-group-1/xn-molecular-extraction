"""Tests for the caption-anchored table method, using geometry taken from the real papers' pages.

Paper 2 page 8 (Table 2): a 7-column table whose header rules are drawn in 7 pieces, with no row lines.
Paper 19 page 5 (Tables 3 and 4): stacked tables with a 6-piece top rule, a group-header underline, an 8-piece
header-bottom rule, and one thin closing rule each.

AI disclosure: Claude (Anthropic) drafted these tests for Peter Adranly; run them before opening a PR.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline import frontend
from pipeline.frontend import RawCell, RawTable

COLS2 = [(51.5, 105.0), (108.0, 170.0), (173.0, 235.0), (238.0, 300.0), (303.0, 380.0), (383.0, 460.0), (463.0, 555.5)]
FULL = (51.5, 555.5)


def pieces(y, spans):
    return [(y, x0, x1) for x0, x1 in spans]


def word(text, x0, yc, width=None, height=8.0):
    width = 4.5 * len(text) if width is None else width
    return {"x0": x0, "y0": yc - height / 2, "x1": x0 + width, "y1": yc + height / 2, "text": text}


def table2_rules():
    banner = pieces(47.0, [FULL]) + pieces(49.5, [FULL]) + pieces(50.5, [FULL])
    return banner + pieces(76.5, COLS2) + pieces(97.5, COLS2) + pieces(289.5, [FULL]) + pieces(290.0, [FULL])


def table2_words():
    words = []
    for i, text in enumerate(["compound", "NB", "NB", "NB", "enzymatic", "enzymatic", "enzymatic"]):
        words.append(word(text, COLS2[i][0] + 4, 82))
    for i, text in enumerate(["name", "(nM)", "(nM)", "(nM)", "(nM)", "(nM)", "(nM)"]):
        words.append(word(text, COLS2[i][0] + 4, 92))
    rows = [["compound", "780", "570", "990", "128", "28", "1661"],
            ["4", "910", "920", "2640", "430", "81", "1298"],
            ["5", ">30,000", ">30,000", ">30,000", "5517", "4171", "2749"]]
    for r, row in enumerate(rows):
        yc = 108 + 11 * r
        for i, text in enumerate(row):
            words.append(word(text, COLS2[i][0] + 4, yc))
    words.insert(0, word("1h", COLS2[0][0] + 4 + 40, 108))                      # "compound 1h": two words, 3 pt apart
    x = 51.5
    for text in ["aN.D.", "=", "Not", "determined,", "N", "=", "1", "for", "enzymatic", "values."]:
        words.append(word(text, x, 280))
        x += 4.5 * len(text) + 3
    return words


CAPTION2 = (51.5, 58.5, 555.4, 70.7)


def test_rule_groups_merge_double_drawn_edges_and_dedupe_pieces():
    groups = frontend.rule_groups(table2_rules())
    near = lambda y: next(g for g in groups if abs(g["y"] - y) < 0.6)
    assert len(near(289.75)["spans"]) == 1 and near(289.75)["coverage"] == pytest.approx(504.0)   # 289.5 + 290.0 -> one rule
    assert len(near(76.5)["spans"]) == 7 and near(76.5)["coverage"] > 480                         # 7 header pieces
    doubled = frontend.rule_groups(pieces(100, [(10, 50), (10.2, 50.3), (60, 100)]))
    assert len(doubled[0]["spans"]) == 2


def test_locate_table_finds_header_rules_and_closing_rule_of_a_borderless_table():
    layout, reason = frontend.locate_table(CAPTION2, frontend.rule_groups(table2_rules()))
    assert reason is None
    assert layout.top_y == pytest.approx(76.5) and layout.header_bottom_y == pytest.approx(97.5)
    assert layout.closing_y == pytest.approx(289.75, abs=0.3)
    assert layout.columns == COLS2 and layout.inner_ys == []


def paper19_rules():
    banner = pieces(47.0, [FULL]) + pieces(49.5, [FULL]) + pieces(50.5, [FULL])
    cols8 = [(51.5 + 63 * i, 51.5 + 63 * i + 60) for i in range(8)]
    group6 = [cols8[0], cols8[1], (cols8[2][0], cols8[3][1]), cols8[4], cols8[5], (cols8[6][0], cols8[7][1])]
    table3 = (pieces(205.5, group6) + pieces(218.5, [(182.4, 290.9), (447.0, 555.5)]) + pieces(219.5, cols8)
              + pieces(232.5, cols8) + pieces(304.0, [FULL]) + pieces(304.5, [FULL]))
    cols4 = [(51.5, 110.0), (113.0, 170.0), (173.0, 231.0), (234.0, 291.5)]
    table4 = (pieces(448.5, [(51.5, 291.5)]) + pieces(449.0, [(51.5, 291.5)]) + pieces(587.5, cols4)
              + pieces(600.5, cols4) + pieces(626.5, [(51.5, 291.5)]) + pieces(627.0, [(51.5, 291.5)]))
    return banner + table3 + table4, cols8, cols4


def test_stacked_tables_are_separated_and_group_underlines_are_not_the_header_bottom():
    rules, cols8, cols4 = paper19_rules()
    groups = frontend.rule_groups(rules)
    table3, why = frontend.locate_table((51.5, 60.7, 555.2, 81.7), groups, next_caption_y=455.7)
    assert why is None
    assert (table3.top_y, table3.header_bottom_y) == (205.5, 232.5) and table3.closing_y == pytest.approx(304.25, abs=0.3)
    assert len(table3.columns) == 8 and len(table3.group_spans) == 6
    assert table3.inner_ys == [pytest.approx(218.5), pytest.approx(219.5)]
    table4, why = frontend.locate_table((51.5, 455.7, 291.5, 477.7), groups)
    assert why is None
    assert (table4.top_y, table4.header_bottom_y) == (587.5, 600.5) and table4.closing_y == pytest.approx(626.75, abs=0.3)
    assert len(table4.columns) == 4


def test_locate_table_explains_why_it_gave_up():
    only_closing = frontend.rule_groups(pieces(300, [FULL]))
    layout, reason = frontend.locate_table(CAPTION2, only_closing)
    assert layout is None and "header rules" in reason
    layout, reason = frontend.locate_table(CAPTION2, frontend.rule_groups(pieces(300, COLS2)))
    assert layout is None and "header rules" in reason                     # one multi-piece rule is not a header
    layout, reason = frontend.locate_table(CAPTION2, frontend.rule_groups(table2_rules()), next_caption_y=200.0)
    assert layout is None and "closing rule" in reason                     # a caption sits before the closing rule


def doubled(y, spans, offset=0.3):
    """A rule whose pieces are drawn twice (rectangle edges), as in the real PDFs: 12 pieces for 6 columns."""
    return pieces(y, spans) + pieces(y, [(a + offset, b + offset) for a, b in spans])


def test_normalize_spans_drops_a_composite_piece_and_merges_doubles():
    cols7 = [(153 + 43 * i, 153 + 43 * i + 42) for i in range(7)]
    assert frontend.normalize_spans([(153, 454)] + cols7) == cols7           # a wide edge beside 7 column pieces
    assert len(frontend.normalize_spans([(10, 50), (10.3, 50.4), (60, 100)])) == 2   # the same piece drawn twice
    assert frontend.normalize_spans([(10, 50), (50.5, 90)]) == [(10, 50), (50.5, 90)]   # touching columns stay apart


def test_row_rules_are_skipped_when_finding_the_closing_rule():
    """Paper 1 page 7: a table with a line under every row, in a block narrower than the page."""
    cols7 = [(153 + 43 * i, 153 + 43 * i + 42) for i in range(7)]
    wide = [(153.0, 454.0)]
    rules = pieces(76.5, wide) + pieces(77.0, cols7) + pieces(106.0, cols7) + pieces(106.5, wide)
    for k in range(15):
        rules += pieces(126.0 + 10 * k, wide) + pieces(126.5 + 10 * k, wide)          # row rules every 10 pt
    rules += pieces(303.5, [FULL]) + pieces(304.0, [FULL])
    layout, reason = frontend.locate_table((51.5, 58.5, 366.2, 70.7), frontend.rule_groups(rules))
    assert reason is None
    assert layout.top_y == pytest.approx(76.75, abs=0.3) and layout.header_bottom_y == pytest.approx(106.25, abs=0.3)
    assert layout.closing_y == pytest.approx(303.75, abs=0.3)                        # not the first row rule at 126
    assert layout.columns == cols7


def test_a_closing_rule_drawn_in_the_headers_own_pieces_is_found():
    """Paper 2 page 5: top, header-bottom and closing rules all drawn as 6 doubled column pieces; no single rule."""
    cols6 = [(63.5 + 36 * i, 63.5 + 36 * i + 35) for i in range(6)]
    rules = pieces(53.5, [(315.5, 555.5)]) + doubled(143.5, cols6) + doubled(170.5, cols6) + doubled(732.0, cols6)
    layout, reason = frontend.locate_table((51.5, 60.0, 261.3, 81.7), frontend.rule_groups(rules))
    assert reason is None
    assert (layout.top_y, layout.header_bottom_y, layout.closing_y) == (pytest.approx(143.65, abs=0.3),
                                                                      pytest.approx(170.65, abs=0.3), pytest.approx(732.15, abs=0.3))
    assert len(layout.columns) == 6


def paper19_page4_rules():
    cols5 = [(51.5 + 48 * i, 51.5 + 48 * i + 45) for i in range(5)]
    cols6 = [(51.5 + 40 * i, 51.5 + 40 * i + 38) for i in range(6)]
    table1 = (pieces(166.0, [(51.5, 291.5)]) + pieces(166.5, [(51.5, 291.5)])                 # rule above the caption
              + pieces(316.0, cols5) + pieces(337.0, [(229.7, 291.5)]) + doubled(338.0, cols6)
              + pieces(351.0, cols6) + pieces(477.5, [FULL]) + pieces(478.0, [FULL]))
    cols6w = [(51.5 + 84 * i, 51.5 + 84 * i + 81) for i in range(6)]
    table2 = (doubled(670.5, cols6w[:4]) + pieces(683.5, [(214.6, 408.5)]) + doubled(684.5, cols6w) + pieces(697.5, cols6w))
    return table1 + table2


def test_a_table_in_one_column_closed_by_a_page_wide_rule_is_found():
    """Paper 19 page 4, Table 1: 240 pt wide, closed by the 504 pt rule that also sits above Table 2's caption."""
    groups = frontend.rule_groups(paper19_page4_rules())
    layout, reason = frontend.locate_table((51.5, 173.2, 291.5, 205.2), groups, next_caption_y=484.9)
    assert reason is None
    assert (layout.top_y, layout.header_bottom_y) == (316.0, 351.0) and layout.closing_y == pytest.approx(477.75, abs=0.3)
    assert len(layout.columns) == 6 and any(abs(y - 337.0) < 0.1 for y in layout.inner_ys)


def test_a_table_cut_by_the_page_gets_a_reason_that_says_so():
    """Paper 19 page 4, Table 2: header rules near the bottom of the page and no closing rule after them."""
    groups = frontend.rule_groups(paper19_page4_rules())
    layout, reason = frontend.locate_table((51.5, 484.9, 555.5, 516.9), groups)
    assert layout is None and "continue on the next page" in reason


def test_extract_grid_builds_header_rows_cells_and_footnote():
    layout, _ = frontend.locate_table(CAPTION2, frontend.rule_groups(table2_rules()))
    grid, notes = frontend.extract_grid(layout, table2_words(), exclude=[])
    assert len(grid) == 4                                                  # header + 3 body rows; the footnote is not a row
    assert grid[0][0].text == "compound name" and grid[0][1].text == "NB (nM)" and grid[0][4].text == "enzymatic (nM)"
    assert [row[0].text for row in grid[1:]] == ["compound 1h", "4", "5"]
    assert grid[1][1].text == "780" and grid[3][2].text == ">30,000" and grid[3][6].text == "2749"
    assert notes.startswith("aN.D. = Not determined")
    assert grid[1][1].bbox[0] == 108.0 and grid[1][1].bbox[2] == 170.0    # cell x-range = the column's rule piece


def test_extract_grid_ignores_words_inside_molecule_boxes():
    layout, _ = frontend.locate_table(CAPTION2, frontend.rule_groups(table2_rules()))
    words = table2_words() + [word("Cl", 130, 150), word("N", 140, 150)]    # atom labels of a drawing inside the table
    with_drawing, _ = frontend.extract_grid(layout, words, exclude=[(120, 140, 160, 160)])
    assert all("Cl" not in c.text and c.text != "N" for row in with_drawing for c in row)
    without_exclusion, _ = frontend.extract_grid(layout, words, exclude=[])
    assert any("Cl" in c.text for row in without_exclusion for c in row)    # they would be read as text otherwise


def test_short_footnotes_with_a_marker_are_notes_not_rows():
    layout, _ = frontend.locate_table(CAPTION2, frontend.rule_groups(table2_rules()))
    base = [w for w in table2_words() if w["y0"] < 200]                       # header + body, without the long footnote
    for text, expected_rows in [("aNot determined.", 4), ("bNone.", 4), ("*Not tested", 4), ("\u2020Estimated", 4)]:
        grid, notes = frontend.extract_grid(layout, base + [word(text, 51.5, 280, width=60)], exclude=[])
        assert len(grid) == expected_rows and notes == text, text
    # a last data row that merely starts with a lowercase letter is still a row
    grid, notes = frontend.extract_grid(layout, base + [word("cAMP", 55, 141), word("12", 112, 141), word("15", 177, 141)], exclude=[])
    assert len(grid) == 5 and grid[-1][0].text == "cAMP" and notes is None      # several cells: not a footnote


def test_the_next_caption_must_be_in_the_same_column():
    right = {"x0": 315.4, "y0": 60.7, "x1": 553.8, "y1": 103.7}
    left_figure = {"x0": 51.5, "y0": 147.4, "x1": 291.5, "y1": 196.4}
    right_table = {"x0": 315.4, "y0": 499.3, "x1": 555.5, "y1": 532.2}
    assert frontend.next_caption_below(right, [left_figure]) is None                 # the other column does not bound it
    assert frontend.next_caption_below(right, [left_figure, right_table]) == 499.3
    full_width = {"x0": 51.5, "y0": 484.9, "x1": 555.5, "y1": 516.9}
    assert frontend.next_caption_below(left_figure, [full_width]) == 484.9           # a full-width caption bounds both columns


def test_a_right_column_table_ignores_rules_and_captions_from_the_left_column():
    """Paper 19 page 8, Table 9: a left-column rule at y=200.5 and a left-column figure caption at y=147."""
    right_cols = [(315.5 + 30 * i, 315.5 + 30 * i + 29) for i in range(8)]
    group7 = right_cols[:6] + [(right_cols[6][0], right_cols[7][1])]
    rules = (pieces(198.5, group7) + pieces(200.5, [(51.5, 291.5)]) + pieces(201.0, [(51.5, 291.5)])     # left column: ignore
             + pieces(219.5, [(490.7, 555.5)]) + doubled(220.5, right_cols) + pieces(233.5, right_cols)
             + pieces(402.5, [(315.5, 555.5)]) + pieces(403.0, [(315.5, 555.5)]))
    groups = frontend.rule_groups(rules)
    left_figure = {"x0": 51.5, "y0": 147.4, "x1": 291.5, "y1": 196.4}
    table9 = {"x0": 315.4, "y0": 60.7, "x1": 553.8, "y1": 103.7}
    layout, reason = frontend.locate_table((315.4, 60.7, 553.8, 103.7), groups, frontend.next_caption_below(table9, [left_figure]))
    assert reason is None
    assert (layout.top_y, layout.header_bottom_y) == (198.5, 233.5) and layout.closing_y == pytest.approx(402.75, abs=0.3)
    assert len(layout.columns) == 8


def sar_layout():
    """Paper 2 page 5, Table 1: six columns from the header rule; drawings (R1, R2, R4) but no readable text."""
    cols = [(63.5 + 36 * i, 63.5 + 36 * i + 35) for i in range(6)]
    return frontend.TableLayout(143.6, 170.6, 732.1, cols, cols, []), cols


def sar_boxes(cols, rows=21):
    """21 compound rows; per row an R1 fragment (col 1), an R2 fragment (col 2) and a taller R4 drawing (col 4)."""
    boxes = []
    for r in range(rows):
        top = 185.0 + 26.0 * r
        boxes.append((cols[1][0] + 3, top + 3, cols[1][0] + 22, top + 20))          # R1
        boxes.append((cols[2][0] + 3, top + 3, cols[2][0] + 22, top + 20))          # R2
        boxes.append((cols[4][0] - 2, top - 3, cols[4][0] + 38, top + 24))          # R4, taller, wider than its column
    return boxes


def test_rows_of_boxes_groups_drawings_of_different_heights_into_compound_rows():
    layout, cols = sar_layout()
    rows = frontend.rows_of_boxes(sar_boxes(cols))
    assert len(rows) == 21 and all(len(r) == 3 for r in rows)
    assert frontend.rows_of_boxes([]) == []
    assert frontend.rows_of_boxes([(0, 0, 10, 10)]) == [[(0, 0, 10, 10)]]


def test_grid_from_drawings_puts_each_drawing_in_its_row_and_column():
    layout, cols = sar_layout()
    grid = frontend.grid_from_drawings(layout, sar_boxes(cols))
    assert len(grid) == 21 and all(len(row) == 6 for row in grid)
    first = grid[0]
    assert all(cell.text == "" for cell in first)
    inside = lambda cell, box: cell.bbox[0] <= box[0] and box[2] <= cell.bbox[2] and cell.bbox[1] <= box[1] and box[3] <= cell.bbox[3]
    boxes = sar_boxes(cols)
    assert inside(first[1], boxes[0]) and inside(first[2], boxes[1]) and inside(first[4], boxes[2])   # R1, R2, R4 columns


def test_a_table_without_a_text_layer_is_built_from_its_drawings_and_marked_partial():
    layout, cols = sar_layout()
    rules = (pieces(layout.top_y, cols) + pieces(layout.header_bottom_y, cols) + pieces(layout.closing_y, [(63.5, 279.4)]))
    boxes = sar_boxes(cols)
    ids = list(range(len(boxes)))[::-1]                                      # detection order is not reading order
    regions = [{"paper_id": "2", "page": 5, "box_id": f"2-p5-{ids[i]}", "x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3],
                "gate": "molecule"} for i, b in enumerate(boxes)]
    caption = {"x0": 51.5, "y0": 60.0, "x1": 261.3, "y1": 81.7, "text": "Table 1. CK1 data for analogs"}
    raw = frontend.table_from_caption(caption, frontend.rule_groups(rules), [], boxes, None)
    assert "detected drawings only" in raw.reason and "OCR" in raw.reason and len(raw.grid) == 22      # header + 21 rows
    record = frontend.table_record("2", 5, 0, raw, [], regions)
    assert record["status"] == "abstain" and len(record["rows"]) == 21 and len(record["columns"]) == 6
    linked = [c["box_id"] for r in record["rows"] for c in r["cells"] if c["box_id"]]
    assert len(linked) == len(set(linked)) == len(boxes)                       # every drawing linked, none twice
    row0 = record["rows"][0]["cells"]
    assert row0[1]["box_id"] == regions[0]["box_id"] and row0[2]["box_id"] == regions[1]["box_id"] and row0[4]["box_id"] == regions[2]["box_id"]
    assert all(c["text"] == "" for r in record["rows"] for c in r["cells"])


def test_a_table_with_no_text_and_no_drawings_says_there_is_no_text_layer():
    layout, cols = sar_layout()
    rules = pieces(layout.top_y, cols) + pieces(layout.header_bottom_y, cols) + pieces(layout.closing_y, [(63.5, 279.4)])
    caption = {"x0": 51.5, "y0": 60.0, "x1": 261.3, "y1": 81.7, "text": "Table 1. An outlined table"}
    raw = frontend.table_from_caption(caption, frontend.rule_groups(rules), [], [(70, 300, 90, 320)], None)   # one stray drawing
    assert "no text layer" in raw.reason and "detected drawings" not in raw.reason


def dense_layout():
    """Six narrow columns 1 pt apart, like paper 2 page 5 and paper 1 page 7: numbers in neighbouring columns sit < 8 pt apart."""
    cols = [(60.0 + 36 * i, 60.0 + 36 * i + 35) for i in range(6)]
    return frontend.TableLayout(100.0, 120.0, 300.0, cols, cols, []), cols


def dense_words(cols, rows=8):
    words = [word(t, cols[i][0] + 2, 110) for i, t in enumerate(["Cpd", "A", "B", "C", "D", "E"])]
    for r in range(rows):
        yc = 135 + 11 * r
        words.append(word(f"{12 + r}a", cols[0][1] - 13.5 - 1, yc))                   # right-aligned labels and numbers
        for i in range(1, 6):
            words.append(word(f"123{r}.{i}5", cols[i][1] - 31.5 - 1, yc))             # 7 characters = 31.5 pt wide
    return words


def test_dense_numeric_rows_in_narrow_columns_are_rows_not_footnotes():
    layout, cols = dense_layout()
    words = dense_words(cols)
    line_gap = min(b["x0"] - a["x1"] for a, b in zip(words[6:12], words[7:13]))
    assert line_gap < frontend.SENTENCE_GAP                                          # the case that fooled the old rule
    grid, notes = frontend.extract_grid(layout, words, exclude=[])
    assert len(grid) == 9 and notes is None                                          # header + 8 rows, nothing taken as a note
    assert grid[8][0].text == "19a" and grid[8][5].text == "1237.55"


def test_a_footnote_crossing_the_columns_is_a_note_even_at_normal_row_spacing():
    layout, cols = dense_layout()
    words = dense_words(cols)
    x = cols[0][0] + 2
    for text in ["aValues", "are", "means", "of", "two", "runs."]:
        words.append(word(text, x, 135 + 11 * 8))                                      # the next line at the normal row spacing
        x += 4.5 * len(text) + 3
    grid, notes = frontend.extract_grid(layout, words, exclude=[])
    assert len(grid) == 9 and notes == "aValues are means of two runs."


def test_a_tight_line_far_below_the_last_row_is_a_note_without_any_marker():
    layout, cols = dense_layout()
    words = dense_words(cols) + [word("Not", cols[0][0] + 2, 135 + 11 * 8 + 25, 14), word("determined", cols[0][0] + 19, 135 + 11 * 8 + 25, 40)]
    grid, notes = frontend.extract_grid(layout, words, exclude=[])
    assert len(grid) == 9 and notes == "Not determined"


def test_only_trailing_lines_can_be_footnotes():
    layout, cols = dense_layout()
    words = dense_words(cols)
    middle = [word("aOdd", cols[0][0] + 2, 135 + 11 * 3 + 5, 20)]                       # marker-like text in the middle of the body
    grid, notes = frontend.extract_grid(layout, words + middle, exclude=[])
    assert notes is None and len(grid) == 10                                          # it stays a row, not a note


def lite_layout():
    cols = [(51.5, 100.0), (104.0, 150.0), (160.0, 200.0), (204.0, 250.0)]
    return frontend.TableLayout(205.5, 232.5, 304.0, cols, [cols[0], cols[1], (160.0, 250.0)], [218.5])


def test_a_header_cell_spanning_columns_is_copied_to_each_of_them():
    layout = lite_layout()
    words = [word("Binding", 165, 211, 28), word("(PoC)", 195, 211, 24),            # group row, above the inner rule
             word("Entry", 55, 225), word("R", 110, 225), word("BRaf", 168, 225), word("MKK4", 210, 225),
             word("10a", 55, 245), word("CH2", 110, 245), word("100", 168, 245), word("94", 210, 245)]
    grid, notes = frontend.extract_grid(layout, words, exclude=[])
    assert [c.text for c in grid[0]] == ["Entry", "R", "Binding (PoC) BRaf", "Binding (PoC) MKK4"]
    assert [c.text for c in grid[1]] == ["10a", "CH2", "100", "94"] and notes is None


def test_a_table_without_rules_becomes_an_abstain_record_not_a_missing_table():
    caption = {"x0": 51.5, "y0": 58.5, "x1": 555.4, "y1": 70.7, "text": "Table 9.  An\nunruled table"}
    raw = frontend.table_from_caption(caption, [], [], [], None)
    assert raw.reason and raw.caption == "Table 9. An unruled table" and raw.grid == []
    record = frontend.table_record("7", 1, 0, raw, [], [])
    assert record["status"] == "abstain" and record["reason"] == raw.reason and record["rows"] == []
    assert record["caption"] == "Table 9. An unruled table" and record["notes"] is None


class P:
    def __init__(self, x, y):
        self.x, self.y = x, y


class FakePage:
    """Just enough of a PyMuPDF page for captioned_tables: drawings with line items, and words."""

    def __init__(self, rule_pieces, words):
        self._pieces, self._words = rule_pieces, words

    def get_drawings(self):
        return [{"items": [("l", P(x0, y), P(x1, y))]} for y, x0, x1 in self._pieces]

    def get_text(self, kind):
        assert kind == "words"
        return [(w["x0"], w["y0"], w["x1"], w["y1"], w["text"], 0, 0, 0) for w in self._words]


def caption_block(text, y0, y1, x1=555.4, page=1, block_id="7-p1-t0"):
    return {"paper_id": "7", "page": page, "block_id": block_id, "x0": 51.5, "y0": y0, "x1": x1, "y1": y1, "text": text,
            "source": "pdf_text"}


def test_captioned_tables_finds_each_table_and_links_its_scaffold_drawing():
    layout = lite_layout()
    rules = (pieces(205.5, layout.group_spans) + pieces(218.5, [(160.0, 250.0)]) + pieces(232.5, layout.columns)
             + pieces(304.0, [(51.5, 250.0)]))
    words = [word("Binding", 165, 211, 28), word("(PoC)", 195, 211, 24), word("Entry", 55, 225), word("R", 110, 225),
             word("BRaf", 168, 225), word("MKK4", 210, 225), word("10a", 55, 245), word("CH2", 110, 245),
             word("100", 168, 245), word("94", 210, 245)]
    page = FakePage(rules, words)
    blocks = [caption_block("Table 3. Affinity of analogues", 60.7, 81.7, x1=250.0),
              caption_block("Figure 9. Something above", 5.0, 20.0, block_id="7-p1-t1")]
    regions = [{"paper_id": "7", "page": 1, "box_id": "7-p1-0", "x0": 80.0, "y0": 100.0, "x1": 220.0, "y1": 195.0, "gate": "molecule"},
               {"paper_id": "7", "page": 1, "box_id": "7-p1-1", "x0": 80.0, "y0": 6.0, "x1": 200.0, "y1": 19.0, "gate": "molecule"}]
    (raw,) = frontend.captioned_tables(page, 1, blocks, regions)
    assert raw.caption == "Table 3. Affinity of analogues" and raw.reason is None
    assert [c.text for c in raw.grid[0]] == ["Entry", "R", "Binding (PoC) BRaf", "Binding (PoC) MKK4"]
    assert [c.text for c in raw.grid[1]] == ["10a", "CH2", "100", "94"]
    record = frontend.table_record("7", 1, 0, raw, [], regions)
    assert record["scaffold_box_id"] == "7-p1-0"                            # inside the block; the box above the caption is ignored
    assert record["bbox"][1] == 205.5 and record["bbox"][3] == 304.0


def test_a_page_without_table_captions_yields_no_tables():
    page = FakePage(pieces(100, COLS2), [])
    assert frontend.captioned_tables(page, 1, [caption_block("Figure 1. A figure", 10, 20)], []) == []
