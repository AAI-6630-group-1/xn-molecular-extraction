#!/usr/bin/env bash
# Every Track 2 (MolSight) result from a fresh clone, in order. Run from the repository root,
# in bash (Git Bash on Windows). The internal papers come from Canvas (see data/README.md).
# On a laptop CPU, BioVista takes about 1.5 hours per MolSight checkpoint. With an NVIDIA GPU,
# install the CUDA build of PyTorch (README.md, Setup step 4) and add --device cuda --batch-size 32
# to the run_molsight.py line: about 25 minutes per checkpoint on an 8 GB laptop GPU.
set -euo pipefail

uv sync                                                    # shared environment: crops and scoring
uv run python benchmarks/willdaly/download_data.py         # BioVista and Patent300; checks data/internal/
uv run python benchmarks/liba-jin/make_crops.py            # Patent300 and internal-paper crops

uv venv benchmarks/liba-jin/.venv-molsight --python 3.11   # MolSight's own environment
PY=benchmarks/liba-jin/.venv-molsight/bin/python
[ -x "$PY" ] || PY=benchmarks/liba-jin/.venv-molsight/Scripts/python.exe   # Windows layout
uv pip install --python "$PY" -r benchmarks/liba-jin/requirements-molsight.txt

for variant in extra stereo; do
  for dataset in biovista patent300 internal; do
    "$PY" benchmarks/liba-jin/run_molsight.py --dataset "$dataset" --variant "$variant"
  done
done

for run in benchmarks/results/liba-jin/*/; do
  uv run python benchmarks/score.py "$run"
done
uv run python benchmarks/liba-jin/compare.py               # comparison.md and comparison.csv
