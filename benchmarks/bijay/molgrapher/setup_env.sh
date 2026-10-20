#!/usr/bin/env bash
# Build the MolGrapher environment on a compute node (srun ... --pty bash). A CPU node is enough.
#
#   XN_ENV_ROOT=$HOME/xn_envs bash molgrapher/setup_env.sh
#
# Follows the MolGrapher README (https://github.com/DS4SD/MolGrapher): Python 3.11, then
# `pip install -e .["gpu"]` from a clone, plus the two fixes in requirements.txt. MolGrapher saves its
# weights under the clone's data/ folder the first time it runs, so run it from the clone (run.sbatch does).
set -euo pipefail

ROOT="${XN_ENV_ROOT:-$HOME/xn_envs}"
ENV_DIR="$ROOT/molgrapher"
SRC_DIR="$ROOT/molgrapher-src"
SHIM_DIR="$ROOT/cuda11_shim"

module load "${XN_CONDA_MODULE:-anaconda3/2024.06}"
conda create -y -p "$ENV_DIR" python=3.11
source activate "$ENV_DIR"
pip install -U pip

[[ -d "$SRC_DIR" ]] || git clone https://github.com/DS4SD/MolGrapher "$SRC_DIR"
( cd "$SRC_DIR" && pip install -e ".[gpu]" )

# pytorch-lightning 2.1.3 imports pkg_resources, which newer setuptools no longer ships.
pip install "setuptools<70"

# The OCR step (PaddlePaddle, built for CUDA 11.7) asks for libcudnn.so, libcublas.so and libcudart.so by
# their unversioned names, and the cluster only has CUDA 12 modules. torch's cu117 wheel bundles CUDA 11
# copies in torch/lib, so link the names Paddle wants to them.
TORCH_LIB="$ENV_DIR/lib/python3.11/site-packages/torch/lib"
mkdir -p "$SHIM_DIR"
ln -sf "$TORCH_LIB/libcudnn.so.8" "$SHIM_DIR/libcudnn.so"
ln -sf "$TORCH_LIB/libcublas.so.11" "$SHIM_DIR/libcublas.so"
ln -sf "$TORCH_LIB/libcublasLt.so.11" "$SHIM_DIR/libcublasLt.so"
ln -sf "$TORCH_LIB"/libcudart-*.so.11.0 "$SHIM_DIR/libcudart.so"

echo "Environment ready: $ENV_DIR"
echo "Use it with: XN_ENV=$ENV_DIR MOLGRAPHER_SRC=$SRC_DIR XN_CUDA11_SHIM=$SHIM_DIR"
echo "MolGrapher commit: $(git -C "$SRC_DIR" rev-parse --short HEAD)"
