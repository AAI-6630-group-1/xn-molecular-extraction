#!/usr/bin/env bash
# Build the DECIMER environment. Run it on a compute node (srun ... --pty bash), not the login
# node, which kills conda. Skip it if you already have a working environment: pass that path as XN_ENV.
#
#   XN_ENV_ROOT=$HOME/xn_envs bash decimer/setup_env.sh      # creates $XN_ENV_ROOT/decimer
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="${XN_ENV_ROOT:-$HOME/xn_envs}/decimer"

module load "${XN_CONDA_MODULE:-anaconda3/2024.06}"
conda create -y -p "$ENV_DIR" python=3.10
source activate "$ENV_DIR"
pip install -U pip
pip install -r "$HERE/requirements.txt"

# Importing DECIMER downloads its weights once; doing it here keeps parallel jobs from racing.
python -c "import tensorflow as tf; from DECIMER import predict_SMILES; print('DECIMER import OK, GPUs:', tf.config.list_physical_devices('GPU'))"
echo "Environment ready: $ENV_DIR   (use it with XN_ENV=$ENV_DIR)"
