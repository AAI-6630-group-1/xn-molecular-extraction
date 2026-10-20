#!/bin/bash
# DECIMER on the BioVista OCSR crops, split over an array of GPU jobs (one shard per task).
# Submit from benchmarks/bijay/ (submit_all.sh does it for you):
#   XN_ENV=<env path> XN_CROPS=<crops dir> sbatch --account=<your account> decimer/run.sbatch
# Quick check first:  XN_LIMIT=50 ... sbatch --array=0-0 ... decimer/run.sbatch
# Asks for an H200: on a V100 (driver 545) TensorFlow 2.20 fails with "cuDNN status 5003" on every crop
# (seen 2026-10-18); it worked on an H200 (driver 570).
#SBATCH --job-name=xn-decimer
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --array=0-3
#SBATCH --output=logs/decimer-%A_%a.out
set -euo pipefail

: "${XN_ENV:?set XN_ENV to the DECIMER conda environment path}"
: "${XN_CROPS:?set XN_CROPS to the folder of BioVista crop PNGs}"
cd "$SLURM_SUBMIT_DIR"
module load "${XN_CONDA_MODULE:-anaconda3/2024.06}"
source activate "$XN_ENV"

LIMIT=(); [[ -n "${XN_LIMIT:-}" ]] && LIMIT=(--limit "$XN_LIMIT")
python common/ocsr_run.py --reader decimer --crops-dir "$XN_CROPS" \
    --out-root "${XN_OUT:-results}" --run-id "${XN_RUN_ID:-$(date +%F)_decimer_biovista}" \
    --shard "${SLURM_ARRAY_TASK_ID}/${SLURM_ARRAY_TASK_COUNT}" --resume "${LIMIT[@]}"
