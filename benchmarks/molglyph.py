"""MolGlyph, BioMiner's recognition model, loaded without installing BioMiner.

BioMiner (Yan et al., 2026, arXiv:2604.21508) reads each molecule drawing with
MolGlyph, a fork of MolScribe that writes MolParser-style extended SMILES
(SMILES plus a description of R-groups and abbreviations) instead of atoms with
coordinates. BioMiner doesn't publish the fork as a package, and the fork reuses
the package name `molscribe`, which would shadow the MolScribe this repo
installs. So this module:

1. fetches the two pieces BioMiner's own OCSR step uses
   (BioMiner/MolScribe/molscribe and BioMiner/commons/molglyph_utils.py) at a
   pinned commit, with a sparse git checkout into a cache folder outside the repo;
2. imports the fork under the name `biominer_molscribe`;
3. runs it the way BioMiner's run_molglyph_batch does: MolGlyph writes a caption,
   and Translator.refactor turns it into a canonical SMILES, expanding
   abbreviations and leaving R-groups as `*` atoms.

The weights (1.7 GB) come from the gated Hugging Face repo jiaxianustc/MolGlyph.
Accept its terms on the model page while logged in, then `hf auth login`, before
the first run.

    from molglyph import MolGlyphReader
    reader = MolGlyphReader(device="cpu")
    reader.predict_images([rgb_array, ...])  # [{"smiles", "caption", "confidence"}, ...]
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import torch
from huggingface_hub import hf_hub_download

BIOMINER_URL = "https://github.com/jiaxianyan/BioMiner.git"
# Latest commit on 2026-10-06. MolGlyph's code has been unchanged since the 2025-12-27 release.
BIOMINER_COMMIT = "17c6161b40e34e2c377b2871f760baab3fdeea06"
WEIGHTS = ("jiaxianustc/MolGlyph", "molglyph_large.pt")
# Only the recognition code; the fork's bundled Indigo libraries are Linux-only and unused here.
SPARSE_PATTERNS = [
    "/BioMiner/MolScribe/molscribe/",
    "!/BioMiner/MolScribe/molscribe/indigo/lib/",
    "/BioMiner/commons/molglyph_utils.py",
    "/BioMiner/commons/abbrevs.csv",
]
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "xn-molecular-extraction"


def fetch_biominer(cache: Path = CACHE) -> Path:
    """Check out BioMiner's recognition code at BIOMINER_COMMIT (once) and return the checkout folder."""
    root = cache / f"biominer-{BIOMINER_COMMIT[:7]}"
    if (root / "BioMiner" / "commons" / "molglyph_utils.py").exists():
        return root
    root.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)

    git("init", "-q")
    git("remote", "add", "origin", BIOMINER_URL)
    git("sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS)
    # A blob-less shallow fetch downloads only the files the sparse checkout keeps.
    git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", BIOMINER_COMMIT)
    git("checkout", "-q", "FETCH_HEAD")
    return root


def _import_as(name: str, path: Path) -> ModuleType:
    """Import a module or package from `path` under `name`, so it can't collide with an installed package."""
    if name in sys.modules:
        return sys.modules[name]
    if path.is_dir():
        spec = importlib.util.spec_from_file_location(name, path / "__init__.py",
                                                      submodule_search_locations=[str(path)])
    else:
        spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MolGlyphReader:
    """MolGlyph plus BioMiner's caption post-processing: RGB crops in, SMILES out."""

    def __init__(self, device: str = "cpu", cache: Path = CACHE):
        root = fetch_biominer(cache)
        fork = _import_as("biominer_molscribe", root / "BioMiner" / "MolScribe" / "molscribe")
        self._utils = _import_as("biominer_molglyph_utils", root / "BioMiner" / "commons" / "molglyph_utils.py")
        self._format_info = sys.modules["biominer_molscribe.utils"].FORMAT_INFO
        self.model = fork.MolGlyph(hf_hub_download(*WEIGHTS), device=torch.device(device))

    def predict_images(self, images: list[np.ndarray], batch_size: int = 16) -> list[dict]:
        """Read each RGB crop. Returns the SMILES, MolGlyph's raw caption, and a confidence per crop.

        This is MolGlyph.predict_images with the decoder called one level down,
        because MolGlyph's own confidence option crashes on caption output. The
        confidence is the geometric mean of the token probabilities, the same
        quantity MolScribe reports as its average token score. An empty SMILES
        means the caption didn't parse into a valid molecule, which BioMiner
        also treats as no output.
        """
        model = self.model
        decoder = model.decoder.decoder["molparser_caption"]
        tokenizer = model.tokenizer["molparser_caption"]
        max_len = self._format_info["molparser_caption"]["max_len"]
        out = []
        for start in range(0, len(images), batch_size):
            batch = [model.transform(image=img, keypoints=[])["image"] for img in images[start:start + batch_size]]
            with torch.no_grad():
                features, _ = model.encoder(torch.stack(batch).to(model.device))
                sequences, scores, *_ = decoder.decode(features, beam_size=1, n_best=1, max_length=max_len)
            for seq, score in zip(sequences, scores):
                caption = tokenizer.sequence_to_smiles(seq[0].tolist())["smiles"]
                out.append({"smiles": self.caption_to_smiles(caption), "caption": caption,
                            "confidence": float(score[0])})
        return out

    def caption_to_smiles(self, caption: str) -> str:
        """BioMiner's post-processing (run_molglyph_batch): expand abbreviations, keep R-groups as `*`."""
        return self._utils.get_refactor(self._utils.Translator.refactor(caption))
