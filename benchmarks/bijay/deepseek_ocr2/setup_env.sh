#!/usr/bin/env bash
# Build the DeepSeek-OCR-2 environment on a compute node (srun ... --pty bash), not the login node.
# A CPU node is enough: flash-attn comes as a ready-made wheel, so nothing is compiled on a GPU.
#
#   XN_ENV_ROOT=$HOME/xn_envs bash deepseek_ocr2/setup_env.sh
#
# Versions follow the model card; see requirements.txt. The CUDA toolkit module must match the CUDA 12.4
# build of torch: cuda/12.3.0 worked on Explorer (11.8 doesn't exist there, and a major-version mismatch
# such as cuda/13.2.0 makes flash-attn refuse to install). List modules with `module avail cuda`.
#
# --no-cache-dir matters: without it the flash-attn install failed with "Invalid cross-device link",
# because it moved its wheel from the node's local disk into pip's cache on the network home folder.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="${XN_ENV_ROOT:-$HOME/xn_envs}/deepseek_ocr2"

module load "${XN_CONDA_MODULE:-anaconda3/2024.06}"
module load "${XN_CUDA_MODULE:-cuda/12.3.0}" || echo "WARNING: no CUDA module loaded; flash-attn may fail to install"
conda create -y -p "$ENV_DIR" python=3.12
source activate "$ENV_DIR"
pip install -U pip
pip install -r "$HERE/requirements.txt"
pip install flash-attn==2.7.3 --no-build-isolation --no-cache-dir
python -c "import flash_attn; print('flash_attn', flash_attn.__version__)"

echo "Environment ready: $ENV_DIR   (use it with XN_ENV=$ENV_DIR)"
