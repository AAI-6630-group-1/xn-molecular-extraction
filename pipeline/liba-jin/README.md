# XN 2.3 module: label linking (Jin, `liba-jin`)

This folder is the XN 2.3 landing page for Jin's module. The code stays in
`pipeline/` beside the other stages, because every stage runs as
`python -m pipeline.<stage>` and imports from the same package.

Full module page (rules, results, open questions):
[`../LINKING.md`](../LINKING.md). Issue: #46. PR: #123.

## What it does

A compound in a paper is drawn in one place and named by a label such as `12a`
somewhere else: under the drawing, or in a table row. Label linking ties each
label to its drawing, and each R-group table row to the scaffold it fills, so
assembly and export can name every molecule. It uses box positions only.

## The code

| File | Role |
|---|---|
| [`../linking.py`](../linking.py) | The module: reads one paper's stage files, writes `links.jsonl` |
| [`../ocr_text.py`](../ocr_text.py) | Optional OCR of the page images (RapidOCR), for labels inside figures |
| [`../requirements-ocr.txt`](../requirements-ocr.txt) | OCR environment, kept apart from the shared one |
| [`../check_linking.py`](../check_linking.py) | Development check on the six internal papers against the answer key |
| [`../tests/test_linking.py`](../tests/test_linking.py) | Tests; fixture paper in `../tests/fixtures/papers/fixture/` |

## Inputs and outputs

Reads, per paper (`papers/<paper_id>/`), as defined in [`../INTERFACES.md`](../INTERFACES.md):

- `text.jsonl`: text lines with boxes (PDF text layer); also `ocr_text.jsonl` if present
- `regions.csv`: molecule boxes from the front end
- `tables.jsonl`: tables, rows and cells from the front end
- `readings.csv`: SMILES per box, used to spot scaffolds (a `*` in the reading)

Writes `links.jsonl`, one record per drawing or table row:
`paper_id link_id box_id label table_id row_id evidence_block_ids status reason`.
`status` is `ok`, `abstain` (not sure, with the reason) or `error`.

## Method and why

1. **Label:** a text line whose whole text is one label (`12a`, `7`, `NR-7h`,
   `(14b)`). Label-shaped text that names something else is skipped: proteins
   (`MKK4`), residues (`Glu179`), atom groups (`NH2`), R positions (`R2`).
2. **Drawing → label:** the closest label below the drawing (or in its lower
   half), within 0.6 drawing heights; a label above counts 1.5 times farther.
   Each label goes to one drawing. Ties and labels taken by a closer drawing abstain.
3. **R-group table row → scaffold:** the front end's `scaffold_box_id`, else the
   closest scaffold above the table on the same page. A drawn cell links to its row.
4. **Activity-table row (no R column) → drawing:** the drawing that got the same label.

Why rules and not a trained model: there is no labelled training data for
label–drawing pairs, the papers follow a strong layout convention (label just
under the drawing), and rules give a reason for every decision, so a wrong link
can be traced. When the rules are unsure they abstain rather than guess.

**Pretrained model:** RapidOCR (ONNX versions of PaddleOCR's PP-OCR text
detector and recognizer), used as is, with no fine-tuning. Chosen because
the labels in these papers are part of the figure images, not the PDF text,
and RapidOCR runs on CPU with a small install (about 120 MB).

**Preprocessing:** pages that hold molecule boxes are rendered at 300 dpi with
PyMuPDF; OCR boxes are converted from pixels back to PDF points (scale 72/300
plus the page's rotation), so they share coordinates with the molecule boxes.
OCR's `l`/`I` next to digits is read as `1` (`1la` → `11a`).

**Data augmentation / transfer learning:** none. Nothing is trained.

## Sample input and output

From the fixture paper (`../tests/fixtures/papers/fixture/`). Input, one drawing
box in `regions.csv` and the text line under it in `text.jsonl`:

```text
fixture,1,fixture-p1-0,100,100,200,180,crops/fixture-p1-0.png,molecule,molecule,0.95,
{"block_id": "fixture-p1-t0", "page": 1, "x0": 140, "y0": 184, "x1": 160, "y1": 194, "text": "12a\n", ...}
```

Output line in `links.jsonl`:

```json
{"paper_id": "fixture", "link_id": "fixture-link1", "box_id": "fixture-p1-0", "label": "12a", "table_id": null, "row_id": null, "evidence_block_ids": ["fixture-p1-t0"], "status": "ok", "reason": "closest label below the drawing"}
```

The full expected output for the fixture (a tie, a drawing with no label, two
R-group rows, a drawn substituent) is
[`expected_links.jsonl`](../tests/fixtures/papers/fixture/expected_links.jsonl),
and `test_fixture_gives_the_expected_links` checks it.

**Real input:** six internal papers, Phase 1 boxes. PDF text alone: 1 link
confirmed by the answer key. With OCR: 50 of 233 boxes linked, 24 confirmed,
2 wrong. On paper 19 with the front end's tables: 48 rows and 12 drawings
linked. Details in [`../LINKING.md`](../LINKING.md).

## Run it

```bash
python -m pipeline.linking <run>/papers/<paper_id>
python -m pytest pipeline/tests/test_linking.py
# optional OCR, in its own environment:
python -m venv .venv-ocr && .venv-ocr/Scripts/pip install -r pipeline/requirements-ocr.txt
.venv-ocr/Scripts/python -m pipeline.ocr_text --paper-dir <run>/papers/<paper_id>
```

AI tool used: Claude Code wrote the code, tests and this page at Jin's request.
