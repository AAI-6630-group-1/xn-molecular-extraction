#!/bin/bash
# MolGrapher on the BioVista OCSR crops, split over an array of GPU jobs (one shard per task).
# Submit from benchmarks/bijay/ (submit_all.sh does it for you):
#   XN_ENV=<env path> MOLGRAPHER_SRC=<clone> XN_CUDA11_SHIM=<shim folder> XN_CROPS=<crops dir> \
#     sbatch --account=<account> molgrapher/run.sbatch
# MolGrapher targets CUDA 11.7, which the H200 can't run, so this asks for a V100 (an A100 also works).
#SBATCH --job-name=xn-molgrapher
#SBATCH --partition=gpu
#SBATCH --gres=gpu:v100-sxm2:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --array=0-3
#SBATCH --output=logs/molgrapher-%A_%a.out
set -euo pipefail

: "${XN_ENV:?set XN_ENV to the MolGrapher conda environment path}"
: "${XN_CROPS:?set XN_CROPS to the folder of BioVista crop PNGs}"
: "${MOLGRAPHER_SRC:?set MOLGRAPHER_SRC to the MolGrapher clone}"
: "${XN_CUDA11_SHIM:?set XN_CUDA11_SHIM to the folder of unversioned CUDA 11 library symlinks}"
export MOLGRAPHER_SRC
BIJAY="$SLURM_SUBMIT_DIR"  # benchmarks/bijay, where sbatch was run
module load "${XN_CONDA_MODULE:-anaconda3/2024.06}"
source activate "$XN_ENV"

# MolGrapher finds its weights under ./data relative to the folder it runs in, so run from its clone.
cd "$MOLGRAPHER_SRC"
# Its OCR step (PaddlePaddle, built for CUDA 11.7) asks for libcudnn.so, libcublas.so, libcudart.so by their
# unversioned names. The shim folder links those names to the CUDA 11 copies bundled inside torch.
export LD_LIBRARY_PATH="$XN_CUDA11_SHIM:$XN_ENV/lib/python3.11/site-packages/torch/lib:${LD_LIBRARY_PATH:-}"

LIMIT=(); [[ -n "${XN_LIMIT:-}" ]] && LIMIT=(--limit "$XN_LIMIT")
python "$BIJAY/common/ocsr_run.py" --reader molgrapher --crops-dir "$XN_CROPS" \
    --out-root "${XN_OUT:-$BIJAY/results}" --run-id "${XN_RUN_ID:-$(date +%F)_molgrapher_biovista}" \
    --shard "${SLURM_ARRAY_TASK_ID}/${XN_NUM_SHARDS:-$SLURM_ARRAY_TASK_COUNT}" --resume "${LIMIT[@]}"
