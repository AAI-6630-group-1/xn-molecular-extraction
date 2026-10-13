#!/bin/bash
#SBATCH --job-name=xn-track3
#SBATCH --partition=gpu-short
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=/scratch/%u/xn/logs/%x-%j.out
#
# Track 3 on the six internal papers with the reader on a GPU, then score the run.
# Arguments go to run_track3.py; give each GPU run its own --tool so it doesn't overwrite a CPU run:
#
#   sbatch hpc/track3_gpu.sbatch --tool moldetv2-molscribe-cuda
#   sbatch hpc/track3_gpu.sbatch --reader molglyph --tool moldetv2-molglyph-cuda
#
# Needs data/internal/ in the cluster clone (hpc/README.md). Results land in
# benchmarks/results/willdaly/<date>_<tool>_internal/; copy them back with hpc/fetch.sh.
# Crops are written to the node's local disk, because home and scratch create small files at a
# few per second (about 0.6 s per box), then packed into one archive on scratch.
set -euo pipefail
source hpc/env.sh
xn_provenance

crop_root="${TMPDIR:-/tmp}/xn-crops-$SLURM_JOB_ID"
trap 'rm -rf "$crop_root"' EXIT
before=$(date +%s)
uv run python benchmarks/willdaly/run_track3.py --device cuda:0 --crop-root "$crop_root" "$@"
run_dir=$(ls -td benchmarks/results/willdaly/*_internal | head -1)
if [ "$(stat -c %Y "$run_dir/run.json")" -lt "$before" ]; then
    echo "no new run folder found" >&2
    exit 1
fi
run_id=$(basename "$run_dir")
mkdir -p "$XN_SCRATCH/crops"
tar -C "$crop_root" -cf "$XN_SCRATCH/crops/$run_id.tar" "$run_id"
uv run python benchmarks/score.py "$run_dir"
echo "run:     $run_dir"
echo "crops:   $XN_SCRATCH/crops/$run_id.tar"
