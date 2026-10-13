# Benchmarks (Phase 1)

Code and results for XN tasks 1.2 and 1.3.

- Put your code in `benchmarks/<your-github-handle>/`. Code more than one person uses (the scorers and readers) lives here in `benchmarks/`.
- Record results in the shared format the team agrees on in [#14](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/14), so task 1.5 can combine them.
- For every result, write down the tool version and the exact command you ran.
- BioMiner setup notes go here once [#18](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/18) is done. Until then, [`molglyph.py`](molglyph.py) runs BioMiner's recognizer, MolGlyph, on a CPU.

## Readers

[`readers.py`](readers.py) loads each molecule recognizer behind one interface, so every reader can get the same crops and the same scorer. It has MolScribe (with the [abbreviation patch](willdaly/README.md#molscribe-bug-and-patch)) and MolGlyph ([`molglyph.py`](molglyph.py)).

```python
sys.path.insert(0, str(REPO / "benchmarks"))
from readers import READERS, load_reader

reader = load_reader("molglyph", device="cpu")
reader.predict(crops)  # RGB arrays in, [{"smiles", "confidence", "raw"}, ...] out
reader.versions        # goes in run.json
```

To add a reader, write a loader that returns those three keys for each crop and register it in `_LOADERS`; the docstring at the top of `readers.py` has the details. [`willdaly/run_biovista.py`](willdaly/run_biovista.py) is a short runner to copy. A tool that needs its own environment (DECIMER needs TensorFlow) can't be loaded this way, so run it there and write `predictions.csv` directly.

## Scoring (draft)

This follows the [proposal on #14](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/14#issuecomment-5841983072) and changes if the team changes it. The scoring rules are explained there; this section covers how to use the scorer.

### Save each run in its own folder

```
benchmarks/results/<your-handle>/<run_id>/
├── run.json          what you ran (you write it)
├── predictions.csv   what the tool output (you write it)
├── scores.csv        written by score.py
└── matches.csv       written by score.py
```

`run_id` is `<YYYY-MM-DD>_<tool>_<dataset>`, for example `2026-10-05_molscribe_internal`. Write only in your own folder, and commit all four files.

**`predictions.csv`** has one row per SMILES the tool output. Only `paper_id` and `smiles` are required.

| Column | Meaning |
|---|---|
| `paper_id` | Article number (1, 2, 4, 6, 16, 19) |
| `smiles` | Exactly as the tool output it; the scorer canonicalizes. Leave out regions where the tool produced nothing |
| `page` | Page number, starting at 1 |
| `x0`, `y0`, `x1`, `y1` | Box in PDF points, origin at the top left |
| `label` | Compound label the tool attached, e.g. `12a` |
| `source` | `drawing` (the default), `name` (looked up from a compound name), `text` (a SMILES printed in the paper), or `unknown` |
| `confidence` | The tool's score, 0 to 1 |

**`run.json`** needs `task` and `dataset`. The rest is for the report.

```json
{
  "handle": "willdaly",
  "tool": "moldetv2-molscribe",
  "track": 3,
  "task": "e2e",
  "dataset": "internal",
  "pipeline": "Docling figures -> MolDetV2 boxes -> MolScribe",
  "versions": {"docling": "x.y.z", "molscribe": "x.y.z", "rdkit": "2026.3.2"},
  "command": "python benchmarks/willdaly/run_track3.py --pdfs data/internal",
  "git_commit": "abc1234",
  "hardware": "M1 Pro 16 GB, CPU only",
  "runtime_s": {"1": 95.2, "2": 140.8},
  "api_cost_usd": null,
  "notes": ""
}
```

### Run the scorer

The scorer needs RDKit 2026.3.2, the sponsor paper's version, because canonical SMILES can change between releases. The shared environment pins it; see [Getting started](../README.md#getting-started).

It reads the ground truth from `data/internal/` (see [data/README.md](../data/README.md)).

```bash
python benchmarks/score.py benchmarks/results/<your-handle>/<run_id>
python benchmarks/score.py --all
```

The first command scores one run and prints a per-paper table. `--all` scores every run and writes `benchmarks/results/summary.csv` for task 1.5.

- **`scores.csv`** has one row per paper, then a `macro` row (the equal-weight average across papers, our headline) and a `pooled` row (all molecules together). In both rows the count columns are sums.
- **`matches.csv`** has one row per unique molecule on each side: every ground-truth molecule is a TP or an FN, and every prediction is a TP or an FP. Each row also gives the most similar molecule on the other side, which is where error analysis starts.

On the internal papers, only `e2e` runs (a PDF in, a set of SMILES out) are scored, because those papers have no ground-truth boxes.

### Patent300: detect, ocsr, and e2e

Runs with `"dataset": "patent300"` are scored by [`score_boxes.py`](score_boxes.py) against [MolMole Patent300](../data/README.md#molmole-patent300), following the MolMole paper's page-level protocol so our numbers line up with its Tables 2 to 4. Boxes are `x0, y0, x1, y1` in pixels of the page image.

| `task` | `paper_id` | Other columns | Metrics in `scores.csv` |
|---|---|---|---|
| `detect` | page stem, e.g. `AU2004259738B2_page_104` | `x0`-`y1`, `confidence` | COCO AP and AR (IoU 0.50 to 0.95), F1 of the two (MolMole Table 2), AP at IoU 0.5, and precision, recall and F1 at IoU 0.5 for boxes scoring at least `score_threshold` from `run.json` (default 0). `best_f1_threshold` is the confidence cut-off with the best F1 |
| `ocsr` | crop ID, e.g. `AU2004259738B2_page_104_bbox_0` | `smiles` | Exact-match accuracy, stereo-blind accuracy, mean Tanimoto; a crop with no output counts as wrong (MolMole Table 3) |
| `e2e` | page stem | `smiles`, `x0`-`y1` | A ground-truth molecule counts as found if the predicted box overlapping it most has IoU of at least 0.5 and the same SMILES. Precision is found / predicted boxes and recall is found / ground-truth boxes (MolMole equation 1, Table 4). `detected50` counts the molecules whose box was found, whatever the SMILES |

For detection, keep low-scoring boxes in `predictions.csv` so AP covers the whole precision-recall curve, and put your tool's operating point in `run.json` as `score_threshold`. `--all` writes each task's runs to its own `summary_<task>_patent300.csv`. `summary.csv` stays e2e on the internal papers, for task 1.5.

MolMole's Tanimoto fingerprint isn't stated; ours is Morgan radius 2, 2048 bits, the same as everywhere else in `score.py`.

### BioVista: ocsr on single-molecule crops

Runs with `"dataset": "biovista"` and `"task": "ocsr"` are scored by [`score_biovista.py`](score_biovista.py) against [BioVista's OCSR set](../data/README.md#biovista-ocsr). `predictions.csv` has one row per crop: `paper_id` is the crop's file stem (for example `51_6rrm_image_molminer_bbox_3-0`) and `smiles` is the tool's output. A crop with no row, or an empty SMILES, counts as no output.

`scores.csv` has one row per subset (`all` crops, BioVista's `test` split) and structure type (`all`, `full`, `chiral`, `markush`, as in BioMiner's OCSR table). Each row gives exact-match accuracy, stereo-blind accuracy and mean Tanimoto, computed as for Patent300, plus `accuracy_biovista`: accuracy under BioVista's own match rule, which neutralizes charges and requires R-group labels to match (except the first `[1*]`). Use `accuracy` to compare runs and `accuracy_biovista` to compare against the BioMiner paper. `--all` writes BioVista runs to `summary_ocsr_biovista.csv`.

### Ground-truth tags

[`gt_tags.csv`](gt_tags.csv) tags each ground-truth row, keyed by `paper_id` and `name`, without the SMILES:

- `name_type`: `public` if a tool could look the name up instead of reading the drawing (a drug name like Axitinib, or a published code like JB170), or `local` if the label only means something inside the paper (like `12a`). `recall_local_names` in `scores.csv` is recall on the `local` molecules only. The current tags are a first pass, so correct them if you know better.
- `challenge`: what the molecule's drawing tests: `single`, `several_in_figure`, `markush_table`, `reaction_scheme`, `macrocycle`, or `large_protac`. Not filled in yet.

### Tests

```bash
pytest benchmarks/tests
```

One test scores the real ground truth against itself. It runs only if the dataset is in `data/internal/`.
