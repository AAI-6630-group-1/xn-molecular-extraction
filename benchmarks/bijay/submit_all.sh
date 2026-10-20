#!/usr/bin/env bash
# Submit all three readers at once, each as its own array of GPU jobs.
# Run from benchmarks/bijay/ on a login node. Needs these set (see README.md):
#   XN_CROPS             folder of BioVista crop PNGs
#   XN_ENV_DECIMER, XN_ENV_MOLGRAPHER, XN_ENV_DEEPSEEK_OCR2   conda environment paths
#   MOLGRAPHER_SRC       the MolGrapher clone (MolGrapher runs from it; recorded in run.json)
#   XN_CUDA11_SHIM       the folder of CUDA 11 symlinks that molgrapher/setup_env.sh creates
#   XN_LIMIT             (optional) read only the first N crops, for a quick check
# This submits 3 arrays of 4 tasks. Explorer rejected a submission that would have put 13 jobs in your queue
# (QOSMaxSubmitJobPerUserLimit) and accepted 9, so if it complains, submit one reader at a time with
# `sbatch` (see README.md).
#
#   ./submit_all.sh <slurm-account>               # full run
#   XN_LIMIT=50 ./submit_all.sh <slurm-account>   # smoke test
set -euo pipefail

ACCOUNT="${1:?usage: ./submit_all.sh <slurm-account>}"
: "${XN_CROPS:?set XN_CROPS}" "${XN_ENV_DECIMER:?set XN_ENV_DECIMER}"
: "${XN_ENV_MOLGRAPHER:?set XN_ENV_MOLGRAPHER}" "${XN_ENV_DEEPSEEK_OCR2:?set XN_ENV_DEEPSEEK_OCR2}"
: "${MOLGRAPHER_SRC:?set MOLGRAPHER_SRC}" "${XN_CUDA11_SHIM:?set XN_CUDA11_SHIM}"
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p logs

STAMP="$(date +%F)"; [[ -n "${XN_LIMIT:-}" ]] && STAMP="smoke-$STAMP"
for reader in decimer molgrapher deepseek_ocr2; do
    env_var="XN_ENV_${reader^^}"
    sbatch --account="$ACCOUNT" \
        --export="ALL,XN_ENV=${!env_var},XN_RUN_ID=${STAMP}_${reader}_biovista" \
        "$reader/run.sbatch"
done
squeue -u "$USER" -o "%i %P %j %T %M %L"
