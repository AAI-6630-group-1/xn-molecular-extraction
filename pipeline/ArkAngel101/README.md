# XN 2.3 module: reading and consensus (Bijay)

The code stays in `pipeline/` beside the other stages, because every stage runs as
`python -m pipeline.<stage>` and imports the shared `stage_io.py`. This folder is
the landing page. Full module page (rule, methods, limits):
[`../READING.md`](../READING.md). Issue: #48 (PR #114). This README holds
everything the 2.3 rubric asks for, so nothing below needs another page.

## Where each 2.3 requirement is

| Requirement | Where in this README |
|---|---|
| What the module does | [What the module does](#what-the-module-does) |
| Inputs and outputs | [Inputs and outputs](#inputs-and-outputs) |
| Pretrained model, preprocessing, augmentation, and why | [Models, preprocessing and why](#models-preprocessing-and-why) |
| Sample input and output | [Sample input and output](#sample-input-and-output) |
| Tests and real runs | [Test evidence](#test-evidence) |
| How to run it | [Run it](#run-it) |

## The code

| File | Role |
|---|---|
| [`../reading.py`](../reading.py) | `consensus_row` and `build_consensus` are the rule; `read_crops` runs the readers and records failures; `read_paper` and `read_run` write the files; `main` is the command line |
| [`../tests/test_reading.py`](../tests/test_reading.py) | 16 tests with fake readers |
| [`../READING.md`](../READING.md) | Longer module page (same content plus the stereochemistry discussion) |

## What the module does

The front end gives this stage cropped images of candidate molecules. The module
reads every crop with two pretrained OCSR (optical chemical structure
recognition) readers, **MolGlyph** and **MolScribe**, then writes one consensus
answer per crop. Label linking, R-group assembly and export read the result.

## Inputs and outputs

| | File | What it holds |
|---|---|---|
| Reads | `papers/<paper_id>/regions.csv` | Front-end regions. Those with `gate` `molecule` or `uncertain` and a `crop_path` are read |
| Reads | `crops/<box_id>.png` | Crop images, relative to the run folder |
| Writes | `papers/<paper_id>/readings.csv` | One row per `(box_id, reader)` for `molglyph` and `molscribe`, plus one `reader=consensus` row per box |
| Updates | `run.json`, `stages.read` | Status, readers, model versions, row and agreement counts |

`readings.csv` columns: `paper_id, box_id, reader, smiles, confidence, raw, status, reason`.
`status` is `ok`, `abstain` (no valid SMILES) or `error` (the reader failed).
Field definitions: [`../INTERFACES.md`](../INTERFACES.md).

## Models, preprocessing and why

- **MolGlyph** (`jiaxianustc/MolGlyph`, `molglyph_large.pt`) is the primary
  reader. It keeps the drawn `*` R-group labels, which assembly needs to match
  table columns to scaffold positions.
- **MolScribe** (`yujieq/MolScribe`, `swin_base_char_aux_1m.pth`) is the second
  vote. On BioVista it fixes MolGlyph's stereochemistry more often than the
  reverse (23 crops against 5).
- DECIMER, MolGrapher and DeepSeek-OCR-2 (my 1.3 benchmark) scored too low to use.
  MolSight and MolNexTR need separate environments and add nothing as a second
  vote ([`reader_overlap.txt`](../../reports/1.4-group-report/reader_overlap.txt)).
- **Preprocessing:** none of my own. Each crop is opened as RGB and passed to the
  reader's own `predict`, which resizes it. Crop padding and DPI are the front
  end's settings. **Augmentation / training:** none; both models are used as
  published (transfer learning is not needed, there is no fine-tuning).
- **Consensus rule (v1):** if both readers give a valid SMILES and RDKit
  canonical forms match, `agree`; if they differ, MolGlyph's row is kept
  (`disagree: molglyph kept`) so its `*` labels survive; if only one is valid,
  that one is used; if neither, `abstain` (or `error` if a reader failed).
  Reader confidences are never used to break ties because they are not calibrated
  against each other.

## Sample input and output

Input: crop `19-p3-2` (paper 19, page 3), a row of `regions.csv` with
`gate=molecule`. Output rows from `readings.csv`
([`../../benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal/papers/19/readings.csv`](../../benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal/papers/19/readings.csv)):

| reader | smiles | status | reason |
|---|---|---|---|
| molglyph | `*N[C@H](*)C(*)=O` (raw ends `<a>0:R</a><a>5:R</a><a>6:Glu7</a>`) | ok | |
| molscribe | `*N[C@@H](*)C(*)=O` (no labels) | ok | |
| consensus | `*N[C@H](*)C(*)=O` (MolGlyph's `raw`) | ok | `disagree: molglyph kept` |

A case where the second reader matters (paper 2, box `2-p4-2`, a BODIPY dye):
MolGlyph abstains, MolScribe reads it, and the consensus row is
`molscribe only: molglyph abstain`. That is the one box where consensus changes
the six-paper score (102 of 120 correct against 101 of 119 with MolGlyph alone).

## Test evidence

`uv run pytest pipeline/tests/test_reading.py` runs 16 tests with fake readers (no
model weights needed): each consensus case, labels surviving into the consensus
row, abstentions kept, reader failure and wrong result count, `uncertain` regions,
`run.json`, and the exit status. All 16 pass.

Real runs:

- Paper 19, 54 crops: [`../../benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal/`](../../benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal)
  (input `regions.csv`, output `readings.csv`, downstream scores).
- All six papers, 233 crops, with this stage in the chain:
  [`../../benchmarks/results/willdaly/2026-11-17_all6-reading_internal/`](../../benchmarks/results/willdaly/2026-11-17_all6-reading_internal).

Consensus outcomes by paper, counted from that run's `readings.csv`:

| Paper | Crops | Agree | Disagree (MolGlyph kept) | MolGlyph only | MolScribe only | Neither |
|---|---|---|---|---|---|---|
| 1 | 18 | 14 | 4 | 0 | 0 | 0 |
| 2 | 74 | 10 | 62 | 0 | 1 | 1 |
| 4 | 77 | 21 | 44 | 10 | 0 | 2 |
| 6 | 2 | 1 | 1 | 0 | 0 | 0 |
| 16 | 8 | 3 | 2 | 3 | 0 | 0 |
| 19 | 54 | 23 | 24 | 7 | 0 | 0 |
| **All** | **233** | **72** | **137** | **20** | **1** | **3** |

## Run it

```bash
uv sync
uv run hf auth login        # account that accepted the MolGlyph terms
uv run python -m pipeline.reading data/pipeline_runs/<run_id>   # --gates molecule to skip uncertain
uv run pytest pipeline/tests/test_reading.py
```

## Limits

- Disagreements are labelled, not resolved; the rule is not tuned on the answer key.
- Stereochemistry is the open choice: v1 always keeps MolGlyph's, and only 7 of
  the 222 internal answer rows are chiral, so a better rule cannot be tested yet.
- Label linking (#46) had not merged when the six-paper run was made.

## AI disclosure

AI tool(s) used: Claude Code. Purpose: wrote `reading.py`, its tests and the
module pages, and ran the tests and the runs. Bijay chose the task and the
starting consensus rule (from `INTERFACES.md`) and reviewed the results.
