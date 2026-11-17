# Reading and consensus (Bijay, #48)

XN task 2.3, module 2 of the pipeline in [README.md](README.md). File formats:
[INTERFACES.md](INTERFACES.md), contract 0.1.

The front end gives this stage cropped images of candidate molecules. This stage
reads each crop with two OCSR (optical chemical structure recognition) readers,
MolGlyph and MolScribe, and picks one answer per crop. Label linking, R-group
assembly and export read the result.

## Inputs and outputs

| | File | What it holds |
|---|---|---|
| Reads | `papers/<paper_id>/regions.csv` | Regions from the front end. Regions with `gate` `molecule` or `uncertain` and a `crop_path` are read; `non_molecule` regions are not |
| Reads | `crops/<box_id>.png` | The crop images, relative to the run folder |
| Writes | `papers/<paper_id>/readings.csv` | One row per `(box_id, reader)` for `molglyph` and `molscribe`, plus one `reader=consensus` row per box |
| Writes | `papers/<paper_id>/links.jsonl` | Created empty only if it does not exist yet, so label linking's output is never overwritten |
| Updates | `run.json`, `stages.read` | Status, readers, gates, device, model versions, row counts, agreement counts, the rule used |

Columns of `readings.csv`: `paper_id, box_id, reader, smiles, confidence, raw, status, reason`.

- `status=ok`: the reader gave a SMILES. `abstain`: it gave nothing valid (the
  row has no SMILES). `error`: the reader failed on that crop (the reason holds
  the exception text).
- `raw` is the reader's untouched output. For MolGlyph it is the SMILES followed
  by `<sep>` and the drawn label of each `*` (`<a>5:A</a>`, `<a>3:R[b]</a>`).
  Assembly uses those labels to match table columns to scaffold positions.
- A consensus row copies `smiles`, `confidence` and `raw` from the reader it
  chose. The reader confidences are not calibrated against each other, so no
  new confidence is made up.

## Consensus rule (version 1)

| Case | Consensus row | `reason` |
|---|---|---|
| Both readers valid, same canonical SMILES | MolGlyph's row | `agree` |
| Both valid, different SMILES | MolGlyph's row | `disagree: molglyph kept` |
| One reader valid | that reader's row | `molglyph only: molscribe abstain` (or `molscribe only: ...`) |
| Neither valid | no SMILES, `status=abstain` | `no reader gave a valid SMILES` |
| Neither valid and a reader failed | no SMILES, `status=error` | `reader failed: <reader>` |

"Valid" means the row is `ok` and RDKit parses its SMILES. Agreement compares
RDKit canonical SMILES with default settings, so atom order does not matter.
Reader confidences are never used to break ties.

Whenever MolGlyph is valid, the consensus row is MolGlyph's row. That keeps its
`raw` labels. If a scaffold took MolScribe's SMILES together with its `raw`,
assembly would find no labels and abstain.

Stereochemistry is the open choice. When the two readers differ only in a
stereocentre, v1 keeps MolGlyph. MolScribe corrects MolGlyph's stereochemistry
on more BioVista crops than the reverse (23 against 5, see
`reports/1.4-group-report/reader_overlap.txt`), so a later rule could take
MolScribe's stereochemistry when the skeletons agree, but it would have to carry
MolGlyph's labels over. That needs chiral crops to test; only 7 of the 222
internal answer rows are chiral.

## Failures are not empty results

A reader that raises, or returns a different number of results than crops, gets
an `error` row for every crop. The other reader still runs. The stage is marked
`error` in `run.json` and `python -m pipeline.reading` exits with status 1.
Nothing turns a failure into a successful empty run.

## Models, preprocessing, and why

- **MolGlyph** (BioMiner's recognizer, `jiaxianustc/MolGlyph molglyph_large.pt`,
  gated on Hugging Face) is the primary reader. It keeps the drawn `*` labels,
  which assembly needs. The team chose it as primary in `INTERFACES.md`.
- **MolScribe** (`yujieq/MolScribe swin_base_char_aux_1m.pth`, with the
  abbreviation patch in `benchmarks/readers.py`) is the second vote.
- MolSight and MolNexTR are not used. On the same 1,000 BioVista crops all three
  work equally well as the second vote (92 to 93% precision) and the others need
  separate environments (`reports/1.4-group-report/reader_overlap.py`).
- **Preprocessing:** none of our own. Each crop is opened as RGB and passed to
  the reader's own `predict`, which does its own resizing. The crop padding and
  DPI are the front end's settings. **Augmentation:** none; the models are used
  as published, with no training or fine-tuning here.
- Models load through `load_reader` in `benchmarks/readers.py`. Both run on a
  laptop CPU; `--device cuda` is only faster.

## Run it

From the repo root, after `uv sync` and a Hugging Face login that has accepted
the MolGlyph terms (`uv run hf auth login`, see `benchmarks/willdaly/README.md`):

```bash
R=data/pipeline_runs/<run_id>          # a front-end run folder
uv run python -m pipeline.reading $R   # --gates molecule to skip uncertain regions
uv run python -m pipeline.assembly $R
uv run python -m pipeline.export $R
uv run python benchmarks/score.py $R
```

`pipeline/read_crops.py` is Will's earlier stand-in. It writes the two reader
rows only, with no consensus row, and this module replaces it.

## Where the code is

| File | What it holds |
|---|---|
| `reading.py` | `consensus_row` and `build_consensus` are the rule; `read_crops` runs the readers and records failures; `read_paper` and `read_run` write the files; `main` is the command line |
| `tests/test_reading.py` | 16 tests with fake readers, so no model weights are needed: each consensus case, the labels surviving into the consensus row, abstentions kept, reader failure and wrong result count, `uncertain` regions, `run.json`, and the exit status |

`uv run pytest pipeline/tests` runs them with the rest of the pipeline tests.

## Sample input and output

Result of the run on paper 19, 54 crops, laptop CPU:
[`benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal/`](../benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal)
holds `run.json`, `papers/19/regions.csv` (input), `papers/19/readings.csv`
(this stage's output), and the downstream `predictions.csv` and scores.

| Reader rows | ok | abstain |
|---|---|---|
| MolGlyph | 54 | 0 |
| MolScribe | 53 | 1 |

Consensus: 23 boxes agree, 24 disagree (MolGlyph kept), 7 are MolGlyph-only.
Scored with the shared scorer, paper 19 gives 59 correct of 62 output (95.2%
precision, 56.7% recall), the same as the stand-in stage's 59 of 62: MolGlyph
was valid on every paper 19 crop, so the consensus row equals the stand-in's
choice here. The stage matters on papers where MolGlyph fails and MolScribe does
not; the other five papers need Peter's front end on them first.

A disagreement that only concerns stereochemistry (box `19-p3-2`), where the
consensus row keeps MolGlyph's labels:

| reader | smiles | raw ends with |
|---|---|---|
| molglyph | `*N[C@H](*)C(*)=O` | `<sep><a>0:R</a><a>5:R</a><a>6:Glu7</a>` |
| molscribe | `*N[C@@H](*)C(*)=O` | the same SMILES, no labels |
| consensus | `*N[C@H](*)C(*)=O` | MolGlyph's `raw`, `disagree: molglyph kept` |

A box one reader could not read (`19-p3-0`): MolScribe abstains, so the consensus
row is MolGlyph's with the reason `molglyph only: molscribe abstain`.

## Limits

- Only paper 19 has been run end to end with this stage.
- Of the 7 MolGlyph-only boxes on paper 19, one is a MolScribe abstention and
  six are MolScribe SMILES that RDKit cannot parse; those count as not valid.
- Disagreements are not resolved, only labelled. A later rule could use
  stereochemistry or the second reader's ring information.
- The rule is not tuned on the answer key.

## AI disclosure

AI tool(s) used: Claude Code. Took Claude Code help.
Specific contribution: it helped write `reading.py`, `tests/test_reading.py` and
this page, and ran the tests and the paper 19 run. Bijay chose the task and the
consensus rule's starting policy (from `INTERFACES.md`), and reviewed the results.
