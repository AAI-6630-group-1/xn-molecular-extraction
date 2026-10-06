#!/usr/bin/env bash
# Rebuild every Track 3 result from scratch, in order (XN task 1.2).
#
#   bash benchmarks/willdaly/reproduce.sh
#
# Run from the repository root. Each step writes run.json and predictions.csv to
# benchmarks/results/willdaly/<date>_<tool>_<dataset>/, and the scoring step adds
# scores.csv and matches.csv. Times are for an M1 Pro on its CPU; about 4.5 hours
# in all, most of it reading BioVista's 8,861 crops twice. Steps are independent
# once the data is in place, so any line can be rerun on its own.
#
# Before running: the internal papers must be in data/internal/ (Canvas, see
# data/README.md), and MolGlyph's gated weights need one click: accept the terms
# at https://huggingface.co/jiaxianustc/MolGlyph while logged in, then `uv run hf auth login`.
set -euo pipefail
cd "$(dirname "$0")/../.."

# 0. Environment (Python 3.11, versions pinned in uv.lock; requirements.txt is the pip equivalent)
uv sync
uv run pytest -q benchmarks/tests

# 1. Data: Patent300 and BioVista download; the internal papers are only checked
uv run python benchmarks/willdaly/download_data.py

# 2. MolMole Patent300 (300 patent pages): detection, recognition on ground-truth crops, and both
uv run python benchmarks/willdaly/run_patent300.py                                         # ~29 min
uv run python benchmarks/willdaly/run_patent300.py --tasks e2e --pad 0 \
    --e2e-tool moldetv2-molscribe-pad0                                                     # ~13 min
uv run python benchmarks/willdaly/run_patent300.py --reader molglyph --tasks ocsr e2e --pad 0 \
    --e2e-tool moldetv2-molglyph-pad0                                                      # ~35 min
uv run python benchmarks/willdaly/run_patent300.py --reader molglyph --tasks e2e         # ~18 min

# 3. BioVista OCSR (8,861 crops): MolScribe and MolGlyph side by side
uv run python benchmarks/willdaly/run_biovista.py --reader molscribe                       # ~45 min
uv run python benchmarks/willdaly/run_biovista.py --reader molglyph                        # ~65 min

# 4. The six internal papers, PDF to SMILES (about 1.5 min each)
uv run python benchmarks/willdaly/run_track3.py
uv run python benchmarks/willdaly/run_track3.py --dpi 200 --tool moldetv2-molscribe-200dpi
uv run python benchmarks/willdaly/run_track3.py --pad 0 --tool moldetv2-molscribe-pad0
uv run python benchmarks/willdaly/run_track3.py --reader molglyph
uv run python benchmarks/willdaly/run_track3.py --reader molglyph --pad 0 --tool moldetv2-molglyph-pad0

# 5. Score every run, then build the side-by-side comparison and error breakdowns
uv run python benchmarks/score.py --all
uv run python benchmarks/willdaly/compare.py
for run in benchmarks/results/willdaly/*_moldetv2-*_internal; do
    uv run python benchmarks/willdaly/analyze_track3.py "$run"
done
