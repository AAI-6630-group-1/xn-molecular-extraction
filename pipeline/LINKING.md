# Label linking (Jin, #46)

`linking.py` reads one paper's stage files and writes `links.jsonl`, with the
fields in [INTERFACES.md](INTERFACES.md). It ties compound labels such as 12a to
drawings, and R-group table rows to their scaffold, using box positions only.

```bash
uv run python -m pipeline.linking data/pipeline_runs/<run_id>/papers/<paper_id>
uv run pytest pipeline/tests/test_linking.py
```

## Rules

1. **Label:** a text record whose whole text is one compound label, such as `12a`,
   `7`, `NR-7h`, `S3` or `(14b)`. Text inside a table is never a drawing's label.
2. **Table rows:** each row links to the table's scaffold. This is the front end's
   `scaffold_box_id` if it is set, otherwise the closest scaffold above the table
   on the same page (a region with role `scaffold`, or one whose reading contains
   `*`). A drawing inside a table cell links to its row.
3. **Other drawings:** the closest label that overlaps the drawing sideways and
   sits below it (or in its lower half), within 0.6 drawing heights. A label
   above the drawing counts 1.5 times farther. Each label goes to one drawing.
4. **Abstain**, with a reason, when there is no label, when two labels are equally
   close, or when a closer drawing already took the label. Non-molecule regions
   get no link. A `scaffold_box_id` that is not a molecule region is an `error`.

## Fixture

`tests/fixtures/papers/fixture/` is a two-page paper made by hand: a complete
drawing with label 12a, a scaffold above a two-row R-group table (one row has a
drawn substituent), a non-molecule plot, a drawing between two equally close
labels, and a drawing with no label. `expected_links.jsonl` is the output the
tests expect.

## First check on the internal papers

`python -m pipeline.check_linking` runs the linker on the six internal papers. It
uses the 233 MolDetV2 boxes and MolGlyph readings from Will's committed Phase 1
run, and no tables. The text comes either from the PDF text layer or from OCR
of the page images. A link is confirmed when the answer key has that label and
its SMILES equals MolGlyph's reading of the box.

| Text records | Boxes linked (of 233) | Confirmed | Wrong | Can't check |
|---|---|---|---|---|
| PDF blocks | 0 | 0 | 0 | 0 |
| PDF lines | 4 | 1 | 0 | 3 |
| PDF words | 22 | 1 | 6 | 15 |
| OCR lines (RapidOCR) | 59 | 27 | 5 | 27 |

In these papers, the labels under drawings are part of the figure images, not
the PDF text, so the text layer has almost nothing to link. The words near the
boxes come mostly from captions and reaction conditions (`140 °C`, `MKK4`).

With OCR, the same rules link 59 boxes: 27 of the 32 links that can be checked
are right. The 5 wrong links took nearby text that looks like a label: a protein
(`NTRK1`), a residue (`Glu179`), an atom group inside the drawing (`NH2`) and two
neighbouring compound names. Of the 163 boxes with no label nearby, 125 are
scaffolds or fragments (MolGlyph's reading has `*`) whose labels sit in R-group
tables, so they need the table step; 30 are complete answer-key molecules whose
label the rules missed.

`ocr_text.py` makes the OCR records. It renders the 29 pages that have boxes at
300 dpi and runs RapidOCR on CPU (about 5 minutes in all), in its own
environment (`requirements-ocr.txt`, about 120 MB to download), and writes
`text.jsonl` records with `source=ocr` to `data/liba-jin/ocr_text/`.

## Next steps

- Skip label-like text that is an atom group (`NH2`) or a protein or residue name.
- Link the scaffolds and fragments through R-group tables, once `tables.jsonl` is
  available.
- Look at the 30 complete molecules whose label was missed, for example labels
  beside the drawing rather than below it.

## Open questions

- OCR: does the front end add OCR text to `text.jsonl`, or does linking run OCR
  itself? Can RapidOCR go in the shared environment?
- Text unit: lines work better than blocks for labels, because a block can merge
  a label with nearby text.
- A table row with no scaffold gets `box_id` null. The contract does not say
  whether `box_id` may be null.
- Cross-page tables are not handled yet; their rows abstain.
- The answer key's names mix labels (`7`), phrases (`Compound 1h`) and drug names
  (`Tivozanib`), so many links cannot be checked automatically.

## AI disclosure

AI tool used: Claude Code. It wrote the module, the fixture, the tests,
`check_linking.py`, `ocr_text.py` and this page at Jin's request, and ran the
checks above.
