"""Download BioMiner's model weights into the Hugging Face cache, at the revisions pinned in
hpc/biominer/env.sh.

Run on a compute node from the repo root, with the repo's own environment:

    source hpc/env.sh && source hpc/biominer/env.sh
    uv run python hpc/biominer/download_weights.py

BioMiner-Instruct and MolGlyph are gated: accept their terms on Hugging Face first, and put a
token at $HF_TOKEN_PATH (hpc/biominer/README.md). About 70 GB in total, nearly all of it
BioMiner-Instruct.
"""

import os

from huggingface_hub import snapshot_download

# (repo, env var holding the revision, files to fetch; None means the whole repo)
WEIGHTS = [
    ("UniParser/MolDetv2", "MOLDETV2_REV", ["moldet_v2_yolo11n_960_doc.pt"]),
    ("jiaxianustc/MolGlyph", "MOLGLYPH_REV", ["molglyph_large.pt", "config.json"]),
    ("jiaxianustc/BioMiner-MinerU-Model", "MINERU_MODELS_REV", None),
    # MinerU 1.3 loads hantian/layoutreader when its config has no local copy; fetch it now
    # so runs don't depend on the network. The .bin duplicates the safetensors.
    ("hantian/layoutreader", "LAYOUTREADER_REV", ["config.json", "model.safetensors"]),
    ("jiaxianustc/BioMiner-Instruct", "BIOMINER_INSTRUCT_REV", None),
]


def main():
    for repo, rev_var, patterns in WEIGHTS:
        revision = os.environ[rev_var]
        path = snapshot_download(repo, revision=revision, allow_patterns=patterns)
        print(f"{repo}@{revision[:7]} -> {path}", flush=True)


if __name__ == "__main__":
    main()
