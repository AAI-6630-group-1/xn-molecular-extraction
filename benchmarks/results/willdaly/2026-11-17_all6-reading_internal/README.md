# All six internal papers, end to end with the reading stage (2026-11-17)

First run of the full Phase 2 chain on all six internal papers, with Bijay's
reading and consensus stage (#48, PR #114) in place of the stand-in
`read_crops.py`. Part of #25.

Code at `main` 0eda0d6, laptop CPU (M1 Pro). Settings and versions are in
`run.json`.

```bash
R=data/pipeline_runs/2026-11-17_all6-reading
uv run python -m pipeline.frontend --table-strategy captions --out $R
uv run python -m pipeline.reading $R
uv run python -m pipeline.assembly $R
uv run python -m pipeline.export $R
uv run python benchmarks/score.py $R
```

Page images, crops and `text.jsonl` are left out (about 119 MB); rerun the
front end to get them. `links.jsonl` is empty because label linking (#46) has
not merged.

## Scores

| Paper | GT | Output | Correct | Precision | Recall |
|---|---|---|---|---|---|
| 1 | 17 | 17 | 17 | 100% | 100% |
| 2 | 34 | 12 | 10 | 83.3% | 29.4% |
| 4 | 60 | 19 | 14 | 73.7% | 23.3% |
| 6 | 1 | 2 | 0 | 0% | 0% |
| 16 | 4 | 8 | 2 | 25.0% | 50.0% |
| 19 | 104 | 62 | 59 | 95.2% | 56.7% |
| Pooled | 220 | 120 | 102 | 85.0% | 46.4% |
| Macro | | | | 62.9% | 43.3% |

Phase 1, same papers (committed `scores.csv` files, not rerun):

| Run | Correct / output | Pooled P | Pooled R |
|---|---|---|---|
| MolDetV2 + MolGlyph (`2026-10-06_moldetv2-molglyph-pad0_internal`) | 64 / 164 | 39.0% | 29.1% |
| BioMiner (`2026-10-13_biominer_internal`) | 73 / 108 | 67.6% | 33.2% |
| This run | 102 / 120 | 85.0% | 46.4% |

## What the consensus rule changed

`ablation_molglyph-only_scores.csv` is the same run with the consensus rows
removed from `readings.csv`, so assembly falls back to MolGlyph (the stand-in's
behaviour). It scores 101 / 119. The one difference is box `2-p4-2`, compound
23 on paper 2 (a BODIPY dye with boron): MolGlyph abstained, MolScribe read it
correctly, and the consensus row kept MolScribe's answer.

Consensus outcomes over 233 crops: 72 agree, 137 disagree (MolGlyph kept),
20 MolGlyph only (19 of them MolScribe SMILES that RDKit cannot parse),
1 MolScribe only, 3 with no valid reading.

Of the 137 disagreements:

| Kind | Boxes |
|---|---|
| MolGlyph has a `*` R-group position, MolScribe writes a fixed group | 102 |
| Different molecules, no `*` | 17 |
| Other cases involving `*` | 13 |
| Stereochemistry only | 5 |

Keeping MolGlyph is right for the first group, since assembly needs its `*`
labels. The 17 no-`*` disagreements are where a better rule could gain.

## Where recall is lost

- 149 of 192 table rows abstain in assembly. Many are activity tables that
  list compounds drawn elsewhere and need label linking (#46).
- 146 drawings are held back by export because a `*` was never resolved.
- Paper 6 (one molecule) is 0 of 1, as in every Phase 1 run.

## AI disclosure

AI tool(s) used: Claude Code.
Purpose: run the pipeline on the six papers, score it, and write this page.
Specific contribution: Claude Code ran the five commands above, the
MolGlyph-only ablation and the disagreement breakdown, checked the paper 2 box
against `matches.csv`, and drafted this README. Will asked for the six-paper
run after #114 merged and decided to commit it.
