"""The two recognizers Track 3 compares, behind one interface.

- molscribe: MolScribe (Qian et al., 2023), GitHub commit 7296a30 with the
  abbreviation patch from smoke_test_track3.py. The recognizer the sponsor
  paper's pipeline used.
- molglyph: MolGlyph, BioMiner's recognizer (Yan et al., 2026), loaded by
  molglyph.py. BioMiner itself needs NVIDIA GPUs and a 32B language model, so
  this is the part of BioMiner that runs on a laptop CPU.

Each reader turns a list of RGB crops into one dict per crop with `smiles`
(empty when the tool gives no valid molecule), `confidence` (the geometric mean
token probability for both models), and `raw` (the tool's untouched output).

    reader = load_reader("molglyph", device="cpu")
    reader.predict(crops)
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from typing import Callable

import numpy as np

READERS = ("molscribe", "molglyph")


@dataclass
class Reader:
    name: str
    predict: Callable[[list[np.ndarray]], list[dict]]
    versions: dict[str, str]


def _molscribe(device: str) -> Reader:
    import torch
    from huggingface_hub import hf_hub_download
    from molscribe import MolScribe
    from smoke_test_track3 import patch_molscribe

    patch_molscribe()
    model = MolScribe(hf_hub_download("yujieq/MolScribe", "swin_base_char_aux_1m.pth"), device=torch.device(device))

    def predict(crops: list[np.ndarray]) -> list[dict]:
        if not crops:
            return []
        preds = model.predict_images(crops, return_confidence=True, batch_size=8)
        # MolScribe writes "<invalid>" when it can't build a molecule; the scorer counts that as invalid output.
        return [{"smiles": p["smiles"], "confidence": float(p["confidence"]), "raw": p["smiles"]} for p in preds]

    return Reader("molscribe", predict, {
        "molscribe": importlib.metadata.version("molscribe") + " (GitHub 7296a30, patched)",
        "molscribe_weights": "yujieq/MolScribe swin_base_char_aux_1m.pth",
    })


def _molglyph(device: str) -> Reader:
    from molglyph import BIOMINER_COMMIT, WEIGHTS, MolGlyphReader

    model = MolGlyphReader(device=device)

    def predict(crops: list[np.ndarray]) -> list[dict]:
        return [{"smiles": p["smiles"], "confidence": p["confidence"], "raw": p["caption"]}
                for p in model.predict_images(crops, batch_size=16)] if crops else []

    return Reader("molglyph", predict, {
        "molglyph_code": f"jiaxianyan/BioMiner {BIOMINER_COMMIT[:7]} (BioMiner/MolScribe, molglyph_utils.py)",
        "molglyph_weights": f"{WEIGHTS[0]} {WEIGHTS[1]}",
    })


def load_reader(name: str, device: str = "cpu") -> Reader:
    """Load one recognizer by name ("molscribe" or "molglyph")."""
    loaders = {"molscribe": _molscribe, "molglyph": _molglyph}
    if name not in loaders:
        raise ValueError(f"unknown reader {name!r}; choose from {', '.join(READERS)}")
    return loaders[name](device)
