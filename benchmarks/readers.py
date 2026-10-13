"""Molecule recognizers (OCSR readers) shared by the team, behind one interface.

- molscribe: MolScribe (Qian et al., 2023), GitHub commit 7296a30 with the
  abbreviation patch below. The recognizer the sponsor paper's pipeline used.
- molglyph: MolGlyph, BioMiner's recognizer (Yan et al., 2026), loaded by
  molglyph.py. BioMiner itself needs NVIDIA GPUs and a 32B language model, so
  this is the part of BioMiner that runs on a laptop CPU.

Each reader turns a list of RGB crops into one dict per crop with `smiles`
(empty when the tool gives no valid molecule), `confidence` (the tool's score,
0 to 1; the geometric mean token probability for both models here), and `raw`
(the tool's untouched output).

    reader = load_reader("molglyph", device="cpu")
    reader.predict(crops)

To add a reader, write a `_<name>(device) -> Reader` loader that keeps that
contract and add it to `_LOADERS`. Import the tool inside the loader, not at the
top of this file, so a missing package only breaks its own reader. A runner in
benchmarks/<handle>/ puts benchmarks/ on sys.path and imports `load_reader`;
benchmarks/willdaly/run_biovista.py is a short example. A tool that needs its
own environment (DECIMER needs TensorFlow) can't be loaded here; run it there
and write `predictions.csv` in the shared results format instead
(benchmarks/README.md).
"""

from __future__ import annotations

import importlib.metadata
import inspect
from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass
class Reader:
    name: str
    predict: Callable[[list[np.ndarray]], list[dict]]
    versions: dict[str, str]


def patch_molscribe() -> None:
    """Fix MolScribe's abbreviation expansion (Ph, OMe, Boc, ...) on this platform.

    molscribe.chemistry._expand_functional_group reads each bond's order *after*
    RWMol.RemoveBond has deleted it. The stale Bond object reports order 0 here
    (macOS arm64, RDKit 2022.09 through 2026.03), so BOND_TYPES[0] raises KeyError
    and every molecule with an abbreviation comes back '<invalid>'. The fix reads
    the orders before removing the bonds. `load_reader("molscribe")` applies it;
    call it yourself before using MolScribe any other way. Calling it again is a
    no-op.
    """
    import molscribe.chemistry as chem

    if getattr(chem, "_xn_patched", False):
        return  # the patched function has no source file, so it can't be patched twice
    src = inspect.getsource(chem._expand_functional_group)
    old_1 = "adjacent_indices = [bond.GetOtherAtomIdx(i) for bond in bonds]"
    old_2 = ("for adjacent_atom, bond in zip(adjacent_atoms, bonds):\n"
             "                    adjacent_atom.SetNumRadicalElectrons(int(bond.GetBondTypeAsDouble()))")
    assert old_1 in src and old_2 in src, "MolScribe source changed; re-check the patch"
    src = src.replace(old_1, old_1 + "\n                bond_orders = [int(b.GetBondTypeAsDouble()) for b in bonds]")
    src = src.replace(old_2, "for adjacent_atom, order in zip(adjacent_atoms, bond_orders):\n"
                             "                    adjacent_atom.SetNumRadicalElectrons(order)")
    exec(src, chem.__dict__)  # redefines _expand_functional_group inside molscribe.chemistry
    chem._xn_patched = True


def _molscribe(device: str) -> Reader:
    import torch
    from huggingface_hub import hf_hub_download
    from molscribe import MolScribe

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


_LOADERS: dict[str, Callable[[str], Reader]] = {"molscribe": _molscribe, "molglyph": _molglyph}
READERS = tuple(_LOADERS)


def load_reader(name: str, device: str = "cpu") -> Reader:
    """Load one recognizer by name (one of READERS)."""
    if name not in _LOADERS:
        raise ValueError(f"unknown reader {name!r}; choose from {', '.join(READERS)}")
    return _LOADERS[name](device)
