# Front end, detection and tables (Peter, #47)

XN task 2.3, module 1 of the pipeline in [README.md](README.md). Landing page: [`PeterAdr14/README.md`](PeterAdr14/README.md). PRs #111 and #113.
Code: [`frontend.py`](frontend.py). Tests: [`tests/test_frontend*.py`](tests). Helper scripts: [`tools/`](tools). File formats: [`INTERFACES.md`](INTERFACES.md).
Its readers are the reading stage ([`READING.md`](READING.md)) and the R-group assembly stage ([`ASSEMBLY_EXPORT.md`](ASSEMBLY_EXPORT.md)).

## What it does

The front end is the first stage of the pipeline. From a PDF of a paper it produces everything later stages need that does not require
reading a molecule: page images, the PDF's own text, the places where molecules are drawn (with a gate that says how sure it is), crops of
those drawings, and the tables of the paper as raw rows and cells, each linked to the drawings and text blocks it contains.

```
PDF -> render pages (300 dpi) -> MolDetV2 finds molecule boxes -> gate + crops   -> regions.csv, crops/
    -> PDF text blocks                                                        -> text.jsonl
    -> "Table N." captions + drawn rules + words, linked to the boxes          -> tables.jsonl
```

## Inputs and outputs

| | |
|---|---|
| Input | One PDF per paper, `<paper_id>.pdf` (default folder `data/internal/`), or any PDF with `--pdf` and `--paper-id` |
| Output folder | A new `--out` directory (an existing one is refused, so a run is never overwritten) |

Per paper, under `<out>/papers/<paper_id>/`:

| File | Content |
|---|---|
| `pages.jsonl` | One record per page: image path, size in pixels and PDF points, rotation, and the pixel-to-PDF matrix (from `smoke.py`) |
| `text.jsonl` | The PDF's text blocks with their boxes (from `smoke.py`) |
| `regions.csv` | One row per detected box: `box_id` (`<paper>-p<page>-<n>`), box in PDF points, `gate` (`molecule`, `uncertain`, `non_molecule`), `confidence`, `reason`, `crop_path`, padded crop box |
| `crops/<box_id>.png` | The cropped drawing (not committed: rendered from the papers) |
| `tables.jsonl` | One record per table: `table_id`, `page`, `bbox`, `scaffold_box_id`, `columns` (headings), `rows` (each with a `label` and `cells`), `status` (`ok` or `abstain`), `reason`, `caption`, `notes` |

Each cell has `text`, its `box`, `evidence_block_ids` (the text blocks it was read from) and `box_id` (the drawing inside it, if any).
`<out>/run.json` records versions, settings, PDF hashes, the commit and a status for each stage. Field definitions: [`INTERFACES.md`](INTERFACES.md).

## Run it

```bash
uv run python -m pipeline.frontend --table-strategy captions --out data/pipeline_runs/frontend-all
uv run python -m pipeline.frontend --check data/pipeline_runs/frontend-all
```

`--check` verifies required fields, unique IDs, and that every `box_id`, `scaffold_box_id` and `evidence_block_ids` reference resolves.
The run also checks itself when it finishes. Options: `--papers`, `--pdf-dir`, `--pdf` with `--paper-id`, `--dpi` (300), `--conf` (0.5),
`--floor` (boxes between floor and conf become `uncertain`; default off), `--pad` (10 px), `--device` (cpu), `--skip-detection` (tables only),
and `--table-strategy` (`captions`, or PyMuPDF's `lines`, `lines_strict`, `text`; the default is still `lines`, so pass `captions` explicitly).

## Where the code is

`frontend.py` is divided into banner-marked sections, in this order:

| Section | Main functions |
|---|---|
| Data types, detector | `Detection`, `RawTable`, `Settings`, `MolDetV2Detector` (the only part that needs the model) |
| Geometry | `transform_box` / `pixel_box_to_pdf` (all four corners, so rotated pages work), `overlap_fraction`, `box_gap` |
| Gate and regions | `gate_detection`, `make_regions` |
| Tables from PyMuPDF | `raw_tables_from_page`, `table_record`, `pick_scaffold`, `blocks_in_cell`, `box_in_cell` |
| Tables from captions and rules | `collect_rule_pieces`, `rule_groups`, `locate_table`, `extract_grid`, `split_two_up`, `grid_from_drawings`, `captioned_tables` |
| Running and checking | `process_paper`, `run_frontend`, `validate_run`, `main` |

Anything that needs PyMuPDF or the model sits in a few thin functions; the rest is plain Python and is tested without a PDF. Tests:
`tests/test_frontend.py` (geometry, gate, records, checks), `tests/test_frontend_captions.py` (the caption method on coordinates taken from the real
papers), `tests/test_frontend_pdf.py` (end to end on synthetic PDFs, including rotated pages). Helper scripts in `tools/` list, show and draw a run's
tables (`list_tables.py`, `show_table.py`, `draw_table_page.py`) and explain why a table is empty (`explain_table.py`, `inspect_page_rules.py`).

## Technical methods

**Pretrained model.** Molecule detection uses MolDetV2 (a YOLO11-nano detector, weights `moldet_v2_yolo11n_960_doc.pt` from the Hugging Face repo
`UniParser/MolDetv2`), run through Ultralytics. It was chosen from the team's own measurements, not from its paper alone: Will's detector sweep
(`benchmarks/willdaly/detector_sweep/README.md`) found 142 of 148 molecules (95.9% recall) on 19 labeled journal pages and 98.9% recall on 428 patent
pages at 960 px and confidence 0.5, and that no larger input size or tiling found any extra molecule on the six internal papers. It is small enough to run
on a CPU. The settings (960 px, 0.5) follow that sweep.

**Transfer learning and augmentation.** None. The front end only runs inference with the weights as released: no fine-tuning, no training, no
augmentation.

**Preprocessing.** Pages are rendered at 300 dpi as RGB with no binarization or denoising. The detector letterboxes each page to 960 px itself, and the
image is flipped to the BGR order Ultralytics expects. Each box is cropped from the full-resolution page with a 10 px margin, and every box is mapped back to
PDF points through the page's pixel-to-PDF matrix (all four corners, so rotated pages stay correct).

**Gate.** A box is `molecule` at confidence >= 0.5, `uncertain` between `--floor` and 0.5, and `non_molecule` if a side is under 16 px or its aspect ratio
exceeds 15:1. Rejected boxes are kept with a reason, never dropped. The thresholds are placeholders and have not been tuned.

**Tables are rule-based, not learned.** PyMuPDF's table finder alone was not enough on the journal tables: with its default settings it found a table region for
9 of the 21 `Table N.` captions in papers 2, 4 and 19, mostly the header band with no data rows, and the text-based setting produced page-sized regions. These
tables draw their header rules as one piece per column, have no row lines, and end in a thin closing rule. So the table method starts at each caption and takes
the columns from the pieces of the header rule, the rows from the text lines below, footnotes from trailing lines that cross the column grid, and copies a
header cell that spans several columns into each column it covers. Words inside detected drawings are ignored, a table printed two compounds per row is split
into one row per compound, and the drawing between the caption and the table becomes `scaffold_box_id`. A table with no text layer (numbers drawn as
outlines) is built from its detected drawings only; one that cannot be built is kept as an `abstain` record with the reason.

## Test evidence

Unit and integration tests: `uv run pytest pipeline/tests` passes (167 tests on `main` when this was written, 64 of them for the front end).

Run on the six internal papers (`benchmarks/results/PeterAdr14/2026-11-10_frontend_internal/`, with `run.json`):

| | Result |
|---|---|
| Molecule boxes | 233 (papers 1, 2, 4, 6, 16, 19: 18, 74, 77, 2, 8, 54), the same count as the team baseline |
| Tables | 25 `Table N.` captions found; 18 built (`ok`); 7 `abstain`, each with its reason in the file |
| Scaffold links | 7 distinct scaffold drawings linked |
| Abstains | no text layer: paper 1 Table 1, paper 2 Table 1 (21 rows built from 56 drawings, text empty); no rule grid (structure-drawing tables): paper 4 Tables 1 and 5, paper 19 Tables 7 and 11; cut by the page edge: paper 19 Table 2 |

**Sample input and output.** Input: `data/internal/19.pdf`, page 8 (paper 19 is J. Med. Chem. 2026, doi:10.1021/acs.jmedchem.6c00689, licensed CC-BY 4.0).
Output for its Table 9, from `uv run python pipeline/tools/show_table.py <run> 19 8 1` (first rows of 13):

```
19-p8-tab0  status=ok  scaffold=19-p8-0
caption: Table 9. Affinity of 7-Azaindoles (A = CH) and 1H- Pyrazolo[3,4-b]pyridines (A = N) to MKK4 and BRaf ...
headings: ['Compound', 'A', 'Ra', 'Rb', 'Rc', 'Rd', 'Binding Affinity [PoC @ 100 nM] MKK4', 'Binding Affinity [PoC @ 100 nM] BRaf']
  19-p8-tab0-r0 ['VMF', 'CH', '-F', '-H', '-H', '-F', '14', '16']
  19-p8-tab0-r1 ['20a', 'CH', '-H', '-H', '-H', '-H', '53', '100']
  19-p8-tab0-r2 ['20b', 'CH', '-F', '-H', '-H', '-H', '16', '31']
  19-p8-tab0-r3 ['20c', 'CH', '-H', '-F', '-H', '-H', '32', '94']
  19-p8-tab0-r4 ['20d', 'CH', '-H', '-H', '-F', '-H', '100', '91']
```

The scaffold drawing above this table is `19-p8-0` in `regions.csv`; the assembly stage joins it with these rows.

**Consumed by the later stages (paper 19).** The reading, assembly and export stages used this module's output unchanged. Bijay ran the reading stage on
paper 19 at commit `793caa0`, which contains this module and its `run.json` (PRs #111 and #113). It read the 54 regions with MolGlyph (54 read) and MolScribe
(53 read, 1 abstained); the consensus matched the readers on 23 boxes and kept MolGlyph's answer on the other 31 (24 disagreements, 7 where only MolGlyph gave a
valid SMILES). Assembly and export then produced 62 molecules, 59 of them correct against the 104-row answer key for paper 19: precision 95.2%, recall 56.7%
(`benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal/scores.csv`). Will's earlier run with a stand-in reading stage gives the same 59 of 62
(`benchmarks/results/willdaly/2026-11-13_p19-*`), because MolGlyph was valid on every crop, so this shows that the stages connect, not how much the front end
adds. Why 45 of the 104 answer rows are matched by no output is not analysed here (see `export_rejections.jsonl` and `matches.csv` in that folder).

**All six papers through the chain.** Will ran the full chain on this module's output for all six papers
(`benchmarks/results/willdaly/2026-11-17_all6-reading_internal/`), and I reproduced it on 2026-11-21 with identical per-paper counts. The chain returned 120
molecules, 102 of them correct against the 220-row answer key (pooled precision 85.0%, recall 46.4%). Per paper (output / correct / answer rows): paper 1:
17 / 17 / 17; paper 2: 12 / 10 / 34; paper 4: 19 / 14 / 60; paper 6: 2 / 0 / 1; paper 16: 8 / 2 / 4; paper 19: 62 / 59 / 104. For comparison, the Phase 1 baseline on
the same papers (MolDetV2 with MolGlyph on every crop, no assembly; `benchmarks/results/willdaly/2026-10-06_moldetv2-molglyph-pad0_internal`, as listed in Will's
README for the run above) gave 64 correct of 164 outputs (39.0% precision, 29.1% recall). Of the 233 crops, 84 were exported directly as complete molecules, 146 were
rejected because a `*` remained in their SMILES (R-group pieces and scaffolds), and 3 were not read by either reader; 43 exported molecules were assembled from a
scaffold and a table row. These are the results of the whole chain (detection, the two readers, assembly and the export rule), not of the front end alone, and papers 6
and 16 have too few answer rows to say much. For paper 2, the records of Table 1 abstain in assembly with "table has no R-group column" (seen on its first rows),
because this module cannot read that table's outlined headings; paper 2's recall is 10 of 34.

## Limits

- Tables with no rule grid and no text layer cannot be read by this method; labels and values of outlined tables need OCR.
- Which R-position a drawn column holds is unknown when its header is outlined (paper 2 Table 1).
- A cell whose text wraps becomes two rows; tables that continue on the next page are not joined.
- With `--skip-detection`, atom labels of drawings can leak into cell text.
- Gate thresholds are untuned; `role` is always `unknown`; `captions` is not yet the default strategy.

## AI disclosure

Claude (Anthropic) drafted `frontend.py`, its tests and the helper scripts, working from page geometry and run output that Peter produced and pasted back.
Peter ran every test and every run on the six papers and checked the output.
