#!/bin/bash
#SBATCH --job-name=xn-biominer-setup
#SBATCH --partition=short
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=03:00:00
#SBATCH --output=/scratch/%u/xn/logs/%x-%j.out
#
# One-time setup for running BioMiner on Explorer. Submit from the repo root:
#
#   sbatch hpc/biominer/setup.sbatch envs      # build the environments (no token needed)
#   sbatch hpc/biominer/setup.sbatch weights   # download the weights (needs the token)
#
# "envs" builds BioMiner's two Python environments and poppler on the node's local disk and
# packs them into $BIOMINER_ENV_TAR on scratch; rerun it after changing a lock file.
# "weights" downloads about 70 GB of weights into $HF_HOME on scratch.
set -euo pipefail
source hpc/env.sh
source hpc/biominer/env.sh
xn_provenance
mode="${1:?usage: sbatch hpc/biominer/setup.sbatch envs|weights}"

if [ "$mode" = weights ]; then
    [ -s "$HF_TOKEN_PATH" ] || { echo "no Hugging Face token at $HF_TOKEN_PATH" >&2; exit 1; }
    uv run python hpc/biominer/download_weights.py
    du -sh "$HF_HOME/hub"/models--{jiaxianustc--BioMiner-Instruct,jiaxianustc--MolGlyph,UniParser--MolDetv2,jiaxianustc--BioMiner-MinerU-Model,hantian--layoutreader}
    exit 0
fi
[ "$mode" = envs ] || { echo "unknown mode: $mode" >&2; exit 1; }

if [ -e "$BIOMINER_ROOT" ]; then
    echo "$BIOMINER_ROOT already exists on $(hostname); is another BioMiner job running here?" >&2
    exit 1
fi
trap 'rm -rf "$BIOMINER_ROOT"' EXIT
mkdir -p "$BIOMINER_ROOT"
df -h /tmp | tail -1

# uv's Python and cache go on local disk too: the Python is part of the archive, and the cache
# would otherwise write tens of thousands of small files to scratch.
export UV_PYTHON_INSTALL_DIR="$BIOMINER_ROOT/python"
export UV_CACHE_DIR="$BIOMINER_ROOT/uv-cache"
for env in main vllm; do
    uv venv --quiet --python 3.10 "$BIOMINER_ROOT/$env"
    uv pip sync --python "$BIOMINER_ROOT/$env/bin/python" --compile-bytecode "hpc/biominer/$env.lock.txt"
done
rm -rf "$UV_CACHE_DIR"

# pdf2image, which BioMiner uses to render pages, calls poppler's pdftoppm; Explorer doesn't
# have it. BioMiner's conda env has 24.09.0 from Anaconda's defaults channel, which needs its
# terms of service accepted; conda-forge's nearest release is 24.08.0.
module load miniconda3/25.9.1
CONDA_PKGS_DIRS="$BIOMINER_ROOT/conda-pkgs" conda create --quiet --yes --prefix "$BIOMINER_ROOT/poppler" \
    --override-channels -c conda-forge poppler=24.08.0
rm -rf "$BIOMINER_ROOT/conda-pkgs"

# Check that each piece loads before packing.
"$BIOMINER_ROOT/poppler/bin/pdftoppm" -v 2>&1 | head -1
java -version 2>&1 | head -1     # py2opsin runs OPSIN, a Java program
"$BIOMINER_ROOT/main/bin/python" -c "
import torch, magic_pdf, ultralytics, litserve, rdkit, onmt, py2opsin, pdf2image, fitz, transformers
from magic_pdf.libs.version import __version__ as mineru
print('main: torch', torch.__version__, 'CUDA', torch.version.cuda, '| magic-pdf', mineru, '| rdkit', rdkit.__version__)"
"$BIOMINER_ROOT/vllm/bin/python" -c "
import torch, vllm, transformers
print('vllm:', vllm.__version__, '| torch', torch.__version__, 'CUDA', torch.version.cuda, '| transformers', transformers.__version__)"

mkdir -p "$(dirname "$BIOMINER_ENV_TAR")"
tar -C "$(dirname "$BIOMINER_ROOT")" -cf "$BIOMINER_ENV_TAR.partial" "$(basename "$BIOMINER_ROOT")"
mv "$BIOMINER_ENV_TAR.partial" "$BIOMINER_ENV_TAR"
echo "envs:    $BIOMINER_ENV_TAR ($(du -h "$BIOMINER_ENV_TAR" | cut -f1), $(find "$BIOMINER_ROOT" | wc -l) files)"
