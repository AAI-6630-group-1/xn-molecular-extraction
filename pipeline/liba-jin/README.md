# XN 2.3 module: label linking (Jin, `liba-jin`)

Landing page for Jin's XN 2.3 module. Issue: #46 (in progress).

Label linking reads `text.jsonl`, `regions.csv`, `tables.jsonl` and
`readings.csv` and writes `links.jsonl` (see [`../INTERFACES.md`](../INTERFACES.md)).
Until it merges, `links.jsonl` is empty and assembly falls back to each table's
own scaffold.

To do before submitting (2.3 rubric): the module code (for example
`pipeline/linking.py`, so it runs as `python -m pipeline.linking`), tests in
`pipeline/tests/`, and a page with inputs and outputs, methods and why, and a
sample input with its output. Link them from this README.
