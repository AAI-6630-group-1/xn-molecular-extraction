#!/usr/bin/env bash
# Record the exact package versions of a working reader environment, so the run is reproducible.
#   XN_ENV=<env path> bash freeze_env.sh decimer      # writes decimer/requirements.lock.txt
set -euo pipefail

READER="${1:?usage: XN_ENV=<env path> bash freeze_env.sh <decimer|molgrapher|deepseek_ocr2>}"
: "${XN_ENV:?set XN_ENV to the conda environment path of the reader}"
cd "$(dirname "${BASH_SOURCE[0]}")"
module load "${XN_CONDA_MODULE:-anaconda3/2024.06}"
source activate "$XN_ENV"
python -m pip freeze > "$READER/requirements.lock.txt"
echo "wrote $READER/requirements.lock.txt ($(wc -l < "$READER/requirements.lock.txt") packages)"
