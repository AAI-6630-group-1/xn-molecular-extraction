# Benchmarks (Phase 1)

Code and results for XN tasks 1.2 and 1.3.

- Put your code in `benchmarks/<your-github-handle>/`.
- Record results in the shared format the team agrees on in [#14](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/14), so task 1.5 can combine them.
- For every result, write down the tool version and the exact command you ran.
- BioMiner setup notes go here once [#18](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/18) is done.

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

The scorer needs RDKit 2026.3.2, the sponsor paper's version, because canonical SMILES can change between releases. Until the shared environment from [#15](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/15) exists:

```bash
pip install -r benchmarks/requirements-score.txt
```

It reads the ground truth from `data/internal/` (see [data/README.md](../data/README.md)).

```bash
python benchmarks/score.py benchmarks/results/<your-handle>/<run_id>
python benchmarks/score.py --all
```

The first command scores one run and prints a per-paper table. `--all` scores every run and writes `benchmarks/results/summary.csv` for task 1.5.

- **`scores.csv`** has one row per paper, then a `macro` row (the equal-weight average across papers, our headline) and a `pooled` row (all molecules together). In both rows the count columns are sums.
- **`matches.csv`** has one row per unique molecule on each side: every ground-truth molecule is a TP or an FN, and every prediction is a TP or an FP. Each row also gives the most similar molecule on the other side, which is where error analysis starts.

Only `e2e` runs (a PDF in, a set of SMILES out) are scored so far. `ocsr` (Track 2) and `detect` (Track 3) come next.

### Ground-truth tags

[`gt_tags.csv`](gt_tags.csv) tags each ground-truth row, keyed by `paper_id` and `name`, without the SMILES:

- `name_type`: `public` if a tool could look the name up instead of reading the drawing (a drug name like Axitinib, or a published code like JB170), or `local` if the label only means something inside the paper (like `12a`). `recall_local_names` in `scores.csv` is recall on the `local` molecules only. The current tags are a first pass, so correct them if you know better.
- `challenge`: what the molecule's drawing tests: `single`, `several_in_figure`, `markush_table`, `reaction_scheme`, `macrocycle`, or `large_protac`. Not filled in yet.

### Tests

```bash
pytest benchmarks/tests
```

One test scores the real ground truth against itself. It runs only if the dataset is in `data/internal/`.
