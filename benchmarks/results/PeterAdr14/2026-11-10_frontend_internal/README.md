# Front end on the six internal papers (2026-11-10)

Output of `pipeline/frontend.py` (PR #111) on papers 1, 2, 4, 6, 16 and 19,
uploaded by Peter on 2026-11-10. Per paper: `pages.jsonl`, `text.jsonl`,
`regions.csv` and `tables.jsonl`, in the layout of `pipeline/INTERFACES.md`.

The page images (`pages/`, about 120 MB) and molecule crops (`crops/`) were left
out, following CONTRIBUTING.md: they are rendered from the papers, and papers 1,
2 and 6 are CC BY-NC-ND. `image_path` in `pages.jsonl` and `crop_path` in
`regions.csv` therefore point at files that are not here. The upload had no
`run.json`. To get the images and run metadata back, rerun the front end:

```bash
uv run python -m pipeline.frontend --table-strategy captions --out data/pipeline_runs/frontend-all
```

The table records need no images, so assembly and table analysis can read
`papers/<paper_id>/tables.jsonl` from this folder directly.
