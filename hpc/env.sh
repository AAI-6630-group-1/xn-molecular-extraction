# Shared settings for jobs on Northeastern's Explorer cluster. Every batch script in hpc/
# sources this from the repo root:
#
#   source hpc/env.sh
#
# Caches go to scratch so home holds only the clone, its data/, and .venv.

export PATH="$HOME/.local/bin:$PATH"
export XN_SCRATCH="/scratch/$USER/xn"
export UV_CACHE_DIR="$XN_SCRATCH/cache/uv"
export UV_LINK_MODE=copy      # home and scratch are separate filesystems, so uv can't hardlink from its cache
export UV_NO_SYNC=1           # `uv run` would otherwise re-sync to the default torch-pypi group (CUDA 13)
# Home and scratch create small files at a few per second, so Python writing a .pyc for every
# module on first import stalled a job for 30 minutes. setup.sbatch compiles them all up front.
export PYTHONDONTWRITEBYTECODE=1
export HF_HOME="$XN_SCRATCH/cache/huggingface"
export TORCH_HOME="$XN_SCRATCH/cache/torch"
mkdir -p "$UV_CACHE_DIR" "$HF_HOME" "$TORCH_HOME" "$XN_SCRATCH/logs"

xn_provenance() {
    # Log where this job ran, on which GPU, and from which commit; save the exact package list.
    echo "job:     ${SLURM_JOB_ID:-none} ${SLURM_JOB_NAME:-} on $(hostname), partition ${SLURM_JOB_PARTITION:-none}"
    echo "commit:  $(git rev-parse --short HEAD)$(git diff --quiet HEAD || echo ' (dirty)')"
    echo "started: $(date -Is)"
    if command -v nvidia-smi >/dev/null; then
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | sed 's/^/gpu:     /'
    fi
    if [ -d .venv ]; then
        uv pip freeze > "$XN_SCRATCH/logs/${SLURM_JOB_ID:-local}-freeze.txt"
        echo "freeze:  $XN_SCRATCH/logs/${SLURM_JOB_ID:-local}-freeze.txt"
    fi
}
