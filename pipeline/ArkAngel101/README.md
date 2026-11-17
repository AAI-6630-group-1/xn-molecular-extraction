# XN 2.3 module: reading and consensus (Bijay, `ArkAngel101`)

Landing page for Bijay's XN 2.3 module. The code stays in `pipeline/` so that
`python -m pipeline.reading` and the shared imports keep working.

Full module page: [`../READING.md`](../READING.md). Issue: #48 (PR #114).

| File | Role |
|---|---|
| [`../reading.py`](../reading.py) | Reads each crop with MolGlyph and MolScribe and adds a consensus row |
| [`../tests/test_reading.py`](../tests/test_reading.py) | Tests |

Sample run (paper 19):
[`../../benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal/`](../../benchmarks/results/ArkAngel101/2026-11-17_p19-reading_internal)

```bash
uv run python -m pipeline.reading data/pipeline_runs/<run_id>
uv run pytest pipeline/tests/test_reading.py
```

Bijay: edit this page as you like before submitting.
