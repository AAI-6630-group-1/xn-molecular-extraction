# Phase 2 pipeline interface proposal

Draft for [#77](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/77),
2026-10-20. Owners follow #76 and still need team confirmation. This defines the
handoffs; it does not claim that the four modules are built.

PDF -> page images and text -> candidate detection and molecule gate -> crops
-> recognition -> label/table linking -> R-group assembly -> SMILES export -> scoring.
Fully drawn molecules bypass assembly. Preserve figure/table context so a
scaffold and its substituents do not become unrelated final predictions.

| Stage and proposed owner | Reads | Writes |
|---|---|---|
| Front end, detection and filter: Peter (`PeterAdr14`) | PDF | `pages.jsonl`, `text.jsonl`, `regions.csv`, crops, `tables.jsonl` with cell geometry/raw text |
| Reading and consensus: Bijay (`ArkAngel101`) | accepted/uncertain crops | `readings.csv`, one row per region and reader |
| Label linking: Jin (`liba-jin`) | text, regions, tables, readings | `links.jsonl`, labels and scaffold/table/row associations with evidence IDs |
| R-group assembly: Will (`willdaly`) | linked scaffolds, substituent readings and table text | `assemblies.jsonl`, full molecules or unresolved records |
| Export and evaluation: Will proposes maintaining the shared adapter; all owners review | eligible readings, links and assemblies | `predictions.csv`, provenance and existing scorer outputs |

## Files and identifiers

`data/pipeline_runs/<run_id>/` holds `run.json`, `predictions.csv`, and
`papers/<paper_id>/` with the stage files above and `pages/0001.png`,
`crops/<box_id>.png`. Image paths are relative to the run root. Copy only small
evaluation outputs into `benchmarks/results/<handle>/<run_id>/` after a complete
real run. HPC jobs keep images on job-local storage and archive them for transfer.

Keep existing `paper_id`, one-based `page`, and `box_id` (e.g. `19-p2-0`). IDs are
unique within a run; compare different runs using PDF hash, page and coordinates.
Boxes use PDF points in the unrotated, crop-relative coordinate system. Page
records include the pixel-to-PDF matrix, rotation, dimensions and DPI.
[INTERFACES.md](INTERFACES.md) defines fields, statuses, joins and export rules.

## Empty output is different from failure

Keep rejected regions as `non_molecule` and uncertain ones as `uncertain`, with a
reason. Readers and assembly return `ok`, `abstain`, or `error`; abstentions have
no SMILES. Never turn an exception into a successful empty run. Stage status in
`run.json` is `complete`, `stub`, `blocked`, or `error`. Unresolved scaffolds and
fragments stay in intermediate files. Log rejections alongside lost recall.

## One-paper smoke command

From the repo root, after `uv sync`:

```bash
uv run python -m pipeline.smoke --pdf data/internal/6.pdf --paper-id 6 --out data/pipeline_runs/smoke-paper6
```

This CPU command runs real PDF rendering/text extraction, then explicit stubs for
detection, reading, linking, assembly and export. It writes the agreed layout,
empty stage files and an empty prediction table. **It verifies plumbing, not
extraction accuracy.** `task=smoke` and `dataset=pipeline-smoke` make the existing
scorer reject it. Output directories must be new. No model downloads are needed.

For a complete six-paper real run, use `task=e2e`, `dataset=internal`, record all
six IDs and exact versions, then use the existing scorer:

```bash
uv run python benchmarks/score.py benchmarks/results/<handle>/<real_run_id>
```

The scorer evaluates every paper in its ground truth, even papers with no output.
A one-paper diagnostic needs a ground-truth subset passed with `--gt`; otherwise
the other five count as missed. Headline evaluation keeps all six and reports
per-paper and equal-weight precision/recall, pooled metrics, unique output counts
and invalid outputs. No salt, stereo or tautomer scoring policy changes here.

## AI disclosure

AI tool(s) used: Codex. Purpose: interface design and CPU smoke scaffold.
Specific contribution: Codex drafted the contract, runner and tests against the
current reader/scorer interfaces. Will and the module owners still need to review
the design. Execution details accompany the 1.4 section draft.
