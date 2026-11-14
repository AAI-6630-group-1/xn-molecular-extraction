# Paper 19 end to end with assembly (2026-11-13)

The first run through the merged Phase 2 modules on one paper: Peter's front
end (`pipeline/frontend.py`), the stand-in reading stage (`pipeline/read_crops.py`,
MolGlyph then MolScribe, no consensus, no label linking), then assembly and
export (`pipeline/assembly.py`, `pipeline/export.py`). Laptop CPU (M1 Pro), about
70 s in all. Versions and settings are in `run.json`.

| Paper | Answer key | Output | Correct | Precision | Recall |
|---|---|---|---|---|---|
| 19 | 104 | 23 | 20 | 87.0% | 19.2% |

Assembly built 1 of 95 table rows (12a, correct). Most rows abstain because a
substituent spelling is missing from `pipeline/substituents.py` (Table 6), the
R group is a linker with two attachment points (Table 3), the scaffold has more
`*` atoms than R columns (Tables 1 and 9, ring-atom columns A/B), or the table
lists compounds drawn elsewhere and has no scaffold (activity tables). The
reasons are in `papers/19/assemblies.jsonl`.

Page images, crops and `text.jsonl` are not committed. To reproduce:

```bash
R=data/pipeline_runs/2026-11-13_p19-assembly
uv run python -m pipeline.frontend --table-strategy captions --papers 19 --out $R
uv run python -m pipeline.read_crops $R
uv run python -m pipeline.assembly $R
uv run python -m pipeline.export $R
uv run python benchmarks/score.py $R
```

To rescore from the committed files only: `uv run python benchmarks/score.py <this folder>`.
These six papers shaped the design, so this is a development benchmark.
