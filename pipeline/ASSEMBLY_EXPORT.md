# R-group assembly, export and scoring (Will, #45)

XN task 2.3, module 4 and 5 of the pipeline in [README.md](README.md). Design
issue: #74. File formats: [INTERFACES.md](INTERFACES.md), contract 0.1.

Many papers draw one scaffold with `R` positions and list the compounds in a
table of substituents. A reader sees the scaffold and the table cells as
separate pieces, so none of those compounds comes out as a molecule. On the six
internal papers this caps recall: papers 2, 4 and 19 hold 198 of the 220
answer-key molecules, most of them drawn this way.

- **Assembly** builds one full molecule per table row from the scaffold and the
  row's substituents, or records why it could not.
- **Export** decides which results of a run become final predictions and writes
  the file the team's scorer already reads.
- **Scoring** is the existing `benchmarks/score.py`, unchanged.

## Run it

From the repo root, after `uv sync` (CPU only, no model downloads):

```bash
uv run python -m pipeline.assembly data/pipeline_runs/<run_id>
uv run python -m pipeline.export data/pipeline_runs/<run_id>
uv run python benchmarks/score.py data/pipeline_runs/<run_id>
uv run pytest pipeline/tests/test_assembly_export.py
```

## Inputs and outputs

| Step | Reads (per paper, under `papers/<paper_id>/`) | Writes |
|---|---|---|
| Assembly | `tables.jsonl` (Peter), `links.jsonl` (Jin), `readings.csv` (Bijay) | `papers/<paper_id>/assemblies.jsonl`, one record per table row |
| Export | `regions.csv`, `readings.csv`, `tables.jsonl`, `links.jsonl`, `assemblies.jsonl` | `predictions.csv`, `provenance.jsonl`, `export_rejections.jsonl` at the run root |
| Both | `run.json` | their status and counts under `stages.assemble` and `stages.export` |

A missing input file stops the run with an error. An empty file means zero
records.

## Where the code is

| File | What it holds |
|---|---|
| `assembly.py` | `join` bonds the pieces; `match_positions` decides which substituent goes where; `find_scaffold` and `read_cell` read one row's inputs; `assemble_row`, `assemble_paper` and `assemble_run` write the records |
| `substituents.py` | The two text lookups: table heading to R position (`R1` is position 1), and cell text to a fragment (`OMe` is `*OC`). 82 spellings of 45 common groups |
| `export.py` | `export_drawings` and `export_assemblies` pick the predictions; `export_run` writes the three files |
| `stage_io.py` | Reading and writing the stage files, and `select_reading`, the rule for choosing one reading per box |
| `phase1_run.py` | Converts a committed Phase 1 benchmark run into a pipeline run folder, so the module runs on real readings before the other modules exist |
| `tests/test_assembly_export.py` | 40 tests; `tests/fixtures/assembly_run/` holds the sample input and expected output |

## How assembly decides

For each row of each table:

1. **Scaffold.** The drawing that label linking tied to the row (a link with
   that `row_id` whose box is not one of the row's cells). If linking left none,
   the table's own `scaffold_box_id`. Two different scaffolds is an abstention.
2. **Substituents.** One per R-group column. A column counts when its heading is
   `R`, `R1`, `R^1`, `Ra` or `R'`; `Compd`, `IC50 (nM)` and other letters such as
   `X` or `Ar` are ignored, so a table that varies `X` abstains. A cell with text is looked up in the abbreviation table. A cell
   with a drawing uses that box's reading, which must have exactly one `*`.
3. **Positions.** Only two cases are certain. Either the scaffold's points are
   numbered (`[1*]`, `[2*]`, how readers write R1 and R2) and every column is
   numbered to match, or the scaffold has one point and the table one R column.
4. **Join.** Each pair of `*` atoms that should meet gets the same atom-map
   number, and RDKit's `molzip` replaces the pair with a bond. The result is
   written as canonical SMILES (`MolToSmiles`, default settings).

Every other case is an abstention with a reason and no SMILES: unknown
substituent text, a drawn cell that is not a one-point fragment, unnumbered
points with several columns, a scaffold position with no column, no linked
scaffold, an invalid product. A malformed record becomes `status=error` for that
row and the run continues. Each record keeps the cell text, how it was read and
the fragment used, so a wrong molecule can be traced to the cell that caused it.

## How export decides

- **A drawing is exported** when its region passed the gate, its selected
  reading is `ok`, the SMILES parses, it has no `*`, and it is not a drawing
  inside a table cell. `source=drawing`, `method=reading`.
- **An assembly is exported** when its status is `ok`. `source=unknown` and
  `method=r_group_assembly`, as the contract asks, because part of the molecule
  may come from table text. Its location is the scaffold's box.
- **Rejected, with a row in `export_rejections.jsonl`:** readings that do not
  parse (`parse_failure`), still contain `*` (`unresolved_wildcard`), or sit in a
  table cell (`table_cell_drawing`).
- **Counted in `run.json`, with no row:** regions the gate turned away, reader
  abstentions, and rows assembly abstained on.

One reading per box: the `consensus` row if the reading module wrote one,
otherwise MolGlyph, otherwise MolScribe (`--readers` changes the order). If the
first of these abstained, the box has no prediction; export does not fall back
to another reader, because that would be a consensus rule and Bijay owns it.
Only `gate=molecule` regions are exported by default; `--gates molecule
uncertain` is the ablation. Nothing is salt-stripped, stereo-stripped or
tautomer-standardized, and the answer key is never read.

## Technical methods

- **Pretrained models.** This module runs none. Its inputs come from the
  models upstream: MolDetV2 boxes (`moldet_v2_yolo11n_960_doc.pt`) and MolGlyph
  readings (`molglyph_large.pt`), with MolScribe as the second reader. They are
  used as released, with no fine-tuning, so there is no transfer learning or
  data augmentation to report for this module.
- **Why rules and not a model.** The step is graph editing, not recognition:
  given the right pieces and positions, the product is determined. RDKit's
  `molzip` does the bonding and handles valence, aromaticity and stereochemistry
  (a stereocentre next to the attachment point keeps its configuration; there is
  a test for it). We call the library rather than editing bonds by hand.
- **Why abstain so readily.** In the Phase 1 experiment, joining every same-page
  pair of one-point fragments gave 582 candidate molecules for 17 correct ones
  (`reports/1.4-group-report/assembly_example.txt`). The sponsor paper reports
  the same pattern for whole pipelines: precision collapses when a tool cannot
  decline (Gulluoglu et al., 2026). So pairing must come from link and table
  evidence, and a missing piece of evidence is an abstention.
- **Preprocessing.** Table text is normalized before lookup: subscript digits
  become plain digits, a leading bond dash and spaces are removed (`–OCH₃`
  becomes `OCH3`). Matching is then exact and case-sensitive. No fuzzy matching
  and no name-to-structure lookup, which the contract disables.
- **Versions.** Python 3.11.14, RDKit 2026.03.2 (the sponsor paper's version,
  and the one `benchmarks/score.py` expects), from the pinned `uv.lock`.

## Test evidence

### Sample input and output (hand-made fixture)

`tests/fixtures/assembly_run/input/` is a two-page paper made by hand, with 10
regions and 4 tables. `expected/` is the module's output, which the tests
compare against. Scaffold `fx-p1-1` reads as `*c1ccc(C(N)=O)cc1` and sits above
this table:

| Compd | R | Result | Why |
|---|---|---|---|
| 13a | `OMe` (text) | `COc1ccc(C(N)=O)cc1` | text looked up as `*OC` |
| 13b | a drawing, read as `*OCC` | `CCOc1ccc(C(N)=O)cc1` | drawn cell joined |
| 13c | `4-F-Ph` (text) | abstain | not in the abbreviation table |
| 13d | `-H` (text) | `NC(=O)c1ccccc1` | hydrogen closes the point |

The other tables cover numbered positions (`[1*]c1ccc([2*])c(C(=O)O)c1` with
R1 = Cl, R2 = CH₃ gives `Cc1ccc(Cl)cc1C(=O)O`), a scaffold with two unnumbered
points and two columns (abstain), and a table with no linked scaffold (abstain).
In all: 8 rows, 5 assembled, 3 abstained. Export writes 7 predictions (2
drawings, 5 assemblies) and 5 rejections (4 with `*`, 1 that does not parse),
and leaves out a plot the gate rejected, an uncertain region and a reader
abstention.

### Real readings: joins

`join` on MolGlyph's actual readings from paper 4, page 3 (boxes `4-p3-5` and
`4-p3-38`):

```
*COc1cccc2c1C(=O)N(C1CCC(=O)NC1=O)C2=O  +  *COCCOCCOCCNC(=O)OC(C)(C)C
->  CC(C)(C)OC(=O)NCCOCCOCCOCCOc1cccc2c1C(=O)N(C1CCC(=O)NC1=O)C2=O
```

That is compound 6 in the answer key. A second test does the same for paper 19's
compound 19. Paper 2's scaffold, read with five unnumbered points, abstains.

### Real readings: export on the six internal papers

No model was rerun. `phase1_run.py` converted the committed MolDetV2 + MolGlyph
run (`2026-10-06_moldetv2-molglyph-pad0_internal`, 233 boxes) into stage files,
with no tables or links, and export and the scorer ran on it on a laptop CPU:

```bash
uv run python -m pipeline.phase1_run benchmarks/results/willdaly/2026-10-06_moldetv2-molglyph-pad0_internal --out data/pipeline_runs/2026-11-10_phase2-export-molglyph-pad0_internal
uv run python -m pipeline.assembly data/pipeline_runs/2026-11-10_phase2-export-molglyph-pad0_internal
uv run python -m pipeline.export data/pipeline_runs/2026-11-10_phase2-export-molglyph-pad0_internal
uv run python benchmarks/score.py data/pipeline_runs/2026-11-10_phase2-export-molglyph-pad0_internal
```

Of the 233 readings, 83 were exported, 145 were rejected for an unresolved `*`,
and 5 were reader abstentions. Unique molecules and correct ones per paper:

| Paper | Answer key | Phase 1: output | Phase 1: correct | Export: output | Export: correct |
|---|---|---|---|---|---|
| 1 | 17 | 17 | 17 | 17 | 17 |
| 2 | 34 | 29 | 10 | 11 | 9 |
| 4 | 60 | 57 | 13 | 18 | 13 |
| 6 | 1 | 2 | 0 | 2 | 0 |
| 16 | 4 | 8 | 2 | 8 | 2 |
| 19 | 104 | 51 | 22 | 23 | 20 |
| Pooled | 220 | 164 | 64 | 79 | 61 |

| | Pooled precision | Pooled recall | Equal-weight precision | Equal-weight recall |
|---|---|---|---|---|
| Phase 1 (every reading) | 39.0% | 29.1% | 37.6% | 37.0% |
| Export (complete molecules only) | 77.2% | 27.7% | 61.0% | 36.2% |

Leaving out fragments halves the output and roughly doubles pooled precision.
It costs 3 correct answers, and all 3 are answer-key rows that are themselves
scaffolds with `*` (paper 2's "cmpd 2 in Scheme 1", paper 19's B9 and "cmpd 2 in
Scheme 2"). The answer key has 5 such rows. See the first open question.

This table measures export only. Assembly produced nothing here because the run
has no tables or links yet, so recall has not moved. The six papers shaped the
design, so they are a development set, not a test of generalization.

## Limits and open questions

- **Scaffolds in the answer key.** The contract says a reading with `*` is not a
  final prediction, but 5 of the 220 answer-key rows are scaffolds. Exporting
  every `*` reading would keep 3 correct answers and add about 80 wrong ones.
  A narrower rule (export a scaffold only when it has a compound label) needs
  label linking first. For the team to decide.
- **No real table has gone through assembly yet.** That needs Peter's
  `tables.jsonl` and Jin's table links. Until then the evidence is the fixture
  and the joins above.
- **Unnumbered points.** MolGlyph reads paper 2's scaffold with five bare `*`,
  so every row of its table abstains. Recovering the R numbers (from the
  reader's raw output or from the labels printed next to the drawing) is the
  next piece of work, and the largest recall gain available.
- **Fragments outside tables.** The 15 molecules the Phase 1 experiment
  recovered in paper 4 came from pairing separately drawn fragments on one
  page. The contract has no link type for "these two drawings are one
  compound", so this module does not join them. Whether a table or a label
  ties those pairs together has not been checked.
- **Substituent text** is limited to the abbreviation table. `4-F-Ph`,
  `morpholin-4-yl` and anything drawn as text formulae beyond the list abstain.
- **Cross-page tables** work only if linking supplies the scaffold; the
  prediction's location is the scaffold's page, and provenance lists the rest.
- **Tables with one row per position** (`R1 = H, R2 = Me` in a caption or a
  transposed table) are not handled.

## Reference

Gulluoglu, H. S. A., Baby, J., Bagul, K. M., Basangari, B. R., Bathini, S. A.,
Chalamalla, N. K. R., Dcunha, J., Gupta, O., Huang, L., Jiang, X., Naidu, Y. R.,
Sathishkumar, G., Sehrawat, M., Thota, S. L., Thuvara, D., Vanguri, M. B.,
Yin, J., Jugder, B.-E., Lusky, I. E., ... Sinitskiy, A. V. (2026). *Practical
use of advanced AI frameworks on real-life scientific problems: Three case
studies* [Preprint]. bioRxiv. https://doi.org/10.64898/2026.06.23.734132

## AI disclosure

AI tool(s) used: Claude Code.
Purpose: implementation, tests and documentation of this module.
Specific contribution: Claude Code wrote `assembly.py`, `export.py`,
`substituents.py`, `stage_io.py`, `phase1_run.py`, the fixture, the tests and
this page on 2026-11-10 at Will's request, following the interface contract and
the design in #74, and ran the tests and the six-paper export reported above.
Will's review of the code and of the design choices listed under "Limits and
open questions" is pending; this section is updated when it is done.
