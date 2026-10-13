#!/bin/bash
#SBATCH --job-name=xn-setup
#SBATCH --partition=short
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:45:00
#SBATCH --output=/scratch/%u/xn/logs/%x-%j.out
#
# Build the pinned environment on a compute node (installs don't belong on the login node),
# then run the tests and check that torch can see a CUDA build. Submit from the repo root:
#
#   sbatch hpc/setup.sbatch
#
# Rerun after any change to uv.lock.
set -euo pipefail
source hpc/env.sh

# Explorer's drivers (545 and 570) predate CUDA 13, so use torch's CUDA 12.6 build (see pyproject.toml).
# --compile-bytecode writes every .pyc now, in parallel, because jobs don't write them (env.sh).
uv sync --frozen --compile-bytecode --no-group torch-pypi --group torch-cu126
xn_provenance
uv run python -c "import torch; print('torch', torch.__version__, '| CUDA build', torch.version.cuda, '| archs', torch.cuda.get_arch_list())"
uv run pytest -q benchmarks/tests
