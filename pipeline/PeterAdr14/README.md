# XN 2.3 module: front end, detection and filter (Peter, `PeterAdr14`)

This folder is the XN 2.3 landing page for Peter's module. The code stays in `pipeline/` beside the other stages, because every stage runs as
`python -m pipeline.<stage>` and imports shared modules. Moving files here would break those commands and the other modules' imports.

Full module page (inputs and outputs, methods, test evidence, limits): [`../FRONTEND.md`](../FRONTEND.md). Issue: #47 (PRs #111, #113).

## The code

| File | Role |
|---|---|
| [`../frontend.py`](../frontend.py) | PDF to page images, text, candidate molecule regions with a gate, crops, and tables built from `Table N.` captions and the drawn rules |
| [`../tools/`](../tools) | Helpers that read a run: `list_tables.py`, `show_table.py`, `draw_table_page.py`, `explain_table.py`, `inspect_page_rules.py` |
| [`../tests/test_frontend.py`](../tests/test_frontend.py), [`test_frontend_captions.py`](../tests/test_frontend_captions.py), [`test_frontend_pdf.py`](../tests/test_frontend_pdf.py) | 64 tests: geometry, gate and records; the caption method on coordinates taken from the real papers; end to end on synthetic PDFs, including rotated pages |

## Inputs and outputs

Reads one PDF per paper. Writes, per paper, `pages.jsonl`, `text.jsonl`, `regions.csv`, `crops/` and `tables.jsonl`, and `run.json` at the run root.
Field definitions: [`../INTERFACES.md`](../INTERFACES.md).

## Where each 2.3 requirement is

| Requirement | Where |
|---|---|
| What the module does, inputs and outputs | [`../FRONTEND.md`](../FRONTEND.md), opening and "Inputs and outputs" |
| Pretrained model, preprocessing, why | "Technical methods" in the module page (MolDetV2 as released; no training, no augmentation) |
| Sample input and output | "Test evidence" in the module page (paper 19, Table 9) |
| Real runs | [`../../benchmarks/results/PeterAdr14/2026-11-10_frontend_internal/`](../../benchmarks/results/PeterAdr14/2026-11-10_frontend_internal) (this module's output on the six papers, with `run.json`) and the full chain on this output, [`../../benchmarks/results/willdaly/2026-11-17_all6-reading_internal/`](../../benchmarks/results/willdaly/2026-11-17_all6-reading_internal) |
| Tests | the three test files above; `uv run pytest pipeline/tests` runs them with the rest |

## Run it

```bash
uv run python -m pipeline.frontend --table-strategy captions --out data/pipeline_runs/<run_id>
uv run python -m pipeline.frontend --check data/pipeline_runs/<run_id>
uv run python pipeline/tools/list_tables.py data/pipeline_runs/<run_id>
uv run pytest pipeline/tests/test_frontend.py pipeline/tests/test_frontend_captions.py pipeline/tests/test_frontend_pdf.py
```

## AI disclosure

AI tool(s) used: Claude (Anthropic).
Purpose: wrote the front-end code, its tests, the helper scripts, and the text of this page and the module page.
Specific contribution: Claude drafted `frontend.py`, the tests, the tools and the documentation from page geometry and run output that Peter produced and
pasted back. Peter ran every test and every run on the six papers and checked the output.
