# XN 2.3 module: front end, detection and filter (Peter, `PeterAdr14`)

Landing page for Peter's XN 2.3 module. The code stays in `pipeline/` so that
`python -m pipeline.frontend` and the shared imports keep working.

Issue: #47 (PRs #111, #113).

| File | Role |
|---|---|
| [`../frontend.py`](../frontend.py) | PDF to page images, text, candidate regions, crops and tables |
| [`../tools/`](../tools) | Table inspection helpers |
| [`../tests/test_frontend.py`](../tests/test_frontend.py), [`test_frontend_captions.py`](../tests/test_frontend_captions.py), [`test_frontend_pdf.py`](../tests/test_frontend_pdf.py) | Tests |

Sample run:
[`../../benchmarks/results/PeterAdr14/2026-11-10_frontend_internal/`](../../benchmarks/results/PeterAdr14/2026-11-10_frontend_internal)

```bash
uv run python -m pipeline.frontend --table-strategy captions --out data/pipeline_runs/<run_id>
uv run pytest pipeline/tests/test_frontend.py pipeline/tests/test_frontend_captions.py pipeline/tests/test_frontend_pdf.py
```

To do before submitting (2.3 rubric): the module has no page like
`READING.md` or `ASSEMBLY_EXPORT.md` yet. Add one here or in this README:
inputs and outputs, the detector and why (MolDetV2 weights, settings),
preprocessing (DPI, padding), and a sample input with its output.
