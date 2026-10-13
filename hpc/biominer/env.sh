# Settings shared by the BioMiner jobs. Sourced after hpc/env.sh:
#
#   source hpc/env.sh && source hpc/biominer/env.sh

# BioMiner's code, pinned to the commit benchmarks/molglyph.py already uses.
export BIOMINER_REPO=https://github.com/jiaxianyan/BioMiner.git
export BIOMINER_COMMIT=17c6161b40e34e2c377b2871f760baab3fdeea06

# Model weights, pinned to Hugging Face revisions (checked 2026-10-13). download_weights.py
# fetches them into $HF_HOME on scratch; run.sbatch links them where BioMiner expects them.
export BIOMINER_INSTRUCT_REV=c865482f8c8b9515f8c9c04806071e27229be9bc    # jiaxianustc/BioMiner-Instruct (gated)
export MOLGLYPH_REV=18db8e0e09dbde08dfc82604ccb815c47d36bff5             # jiaxianustc/MolGlyph (gated)
export MOLDETV2_REV=88b3836ae4fe692dd2d4c123b4aa0d4a5039eb75             # UniParser/MolDetv2
export MINERU_MODELS_REV=b3f7c96c9e49193ebfb2328cea651129e8f6b9c3        # jiaxianustc/BioMiner-MinerU-Model
export LAYOUTREADER_REV=629be376d86fbab624ddc4020804a4e93b5515bc         # hantian/layoutreader

# Both environments and poppler live under one fixed path on the node's local disk. Virtual
# environments record absolute paths, so the setup job builds them here and every run job
# unpacks the archive to the same place. Home and scratch create small files at a few per
# second, which would make a 100,000-file environment unusable there.
export BIOMINER_ROOT="/tmp/$USER-biominer"
export BIOMINER_ENV_TAR="$XN_SCRATCH/biominer/envs.tar"

# The token for the gated models stays in home, readable only by you; HF_HOME is on scratch.
export HF_TOKEN_PATH="$HOME/.cache/huggingface/token"

hf_snapshot() {
    # Path of a pinned snapshot in the Hugging Face cache: hf_snapshot <org/name> <revision>
    echo "$HF_HOME/hub/models--${1//\//--}/snapshots/$2"
}
