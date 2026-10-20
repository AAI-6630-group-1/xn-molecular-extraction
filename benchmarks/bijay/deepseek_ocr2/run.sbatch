#!/bin/bash
# DeepSeek-OCR-2 on the BioVista OCSR crops, split over an array of GPU jobs (one shard per task).
# Submit from benchmarks/bijay/ (submit_all.sh does it for you):
#   XN_ENV=<env path> XN_CROPS=<crops dir> sbatch --account=<your account> deepseek_ocr2/run.sbatch
# Needs bf16 and FlashAttention, which V100s lack, so this asks for an A100.
#SBATCH --job-name=xn-deepseek-ocr2
#SBATCH --partition=gpu
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --array=0-3
#SBATCH --output=logs/deepseek_ocr2-%A_%a.out
set -euo pipefail

: "${XN_ENV:?set XN_ENV to the DeepSeek-OCR-2 conda environment path}"
: "${XN_CROPS:?set XN_CROPS to the folder of BioVista crop PNGs}"
cd "$SLURM_SUBMIT_DIR"
module load "${XN_CONDA_MODULE:-anaconda3/2024.06}"
source activate "$XN_ENV"

LIMIT=(); [[ -n "${XN_LIMIT:-}" ]] && LIMIT=(--limit "$XN_LIMIT")
python common/ocsr_run.py --reader deepseek_ocr2 --crops-dir "$XN_CROPS" --chunk 8 \
    --out-root "${XN_OUT:-results}" --run-id "${XN_RUN_ID:-$(date +%F)_deepseek_ocr2_biovista}" \
    --shard "${SLURM_ARRAY_TASK_ID}/${SLURM_ARRAY_TASK_COUNT}" --resume "${LIMIT[@]}"
