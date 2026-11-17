# XN 2.3 module: R-group assembly, export and scoring (Will, `willdaly`)

This folder is the XN 2.3 landing page for Will's module. The code stays in
`pipeline/` beside the other stages, because every stage runs as
`python -m pipeline.<stage>` and imports the shared `stage_io.py`. Moving files
here would break those commands and the other modules' imports.

Full module page (inputs and outputs, design, methods, test evidence, limits):
[`../ASSEMBLY_EXPORT.md`](../ASSEMBLY_EXPORT.md). Issue: #45 (design #74).

## The code

| File | Role |
|---|---|
| [`../assembly.py`](../assembly.py) | Builds one molecule per R-group table row, or records why it can't |
| [`../join.py`](../join.py) | Matches table columns to `*` positions and bonds the pieces with RDKit `molzip` |
| [`../substituents.py`](../substituents.py) | Heading-to-position and cell-text-to-fragment lookups |
| [`../export.py`](../export.py) | Picks the final predictions; writes `predictions.csv`, `provenance.jsonl`, `export_rejections.jsonl` |
| [`../stage_io.py`](../stage_io.py) | Shared reading and writing of stage files |
| [`../phase1_run.py`](../phase1_run.py) | Turns a Phase 1 benchmark run into a pipeline run folder |
| [`../tests/test_assembly_export.py`](../tests/test_assembly_export.py) | Tests; fixture in `../tests/fixtures/assembly_run/` |

## Inputs and outputs

Reads `tables.jsonl`, `links.jsonl`, `readings.csv` and `regions.csv` per paper.
Writes `assemblies.jsonl` per paper and `predictions.csv` at the run root, which
`benchmarks/score.py` scores. Field definitions: [`../INTERFACES.md`](../INTERFACES.md).

## Where each 2.3 requirement is

| Requirement | Where |
|---|---|
| What the module does, inputs and outputs | [`../ASSEMBLY_EXPORT.md`](../ASSEMBLY_EXPORT.md), opening and "Inputs and outputs" |
| Pretrained models, preprocessing, why | "Technical methods" in the module page |
| Sample input and output | "Test evidence" in the module page (hand-made fixture) |
| Real run | [`../../benchmarks/results/willdaly/2026-11-17_all6-reading_internal/`](../../benchmarks/results/willdaly/2026-11-17_all6-reading_internal) (all six papers) |

## Run it

```bash
uv run python -m pipeline.assembly data/pipeline_runs/<run_id>
uv run python -m pipeline.export data/pipeline_runs/<run_id>
uv run python benchmarks/score.py data/pipeline_runs/<run_id>
uv run pytest pipeline/tests/test_assembly_export.py
```

## AI disclosure

AI tool(s) used: Claude Code.
Purpose: set up this landing page.
Specific contribution: Claude Code wrote this page from the existing module
page and file list. Will asked for one folder per teammate for XN 2.3.
