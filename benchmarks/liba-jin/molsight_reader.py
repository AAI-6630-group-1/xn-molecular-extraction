"""MolSight (Zhang et al., AAAI 2026), loaded as an OCSR reader for the team benchmark.

MolSight reads one molecule crop with an EfficientViT-L1 encoder and a 6-layer
Transformer decoder that writes SMILES. It is trained in three stages: SMILES
pretraining, fine-tuning with bond and atom-position targets, and GRPO
reinforcement learning on 200k stereoisomers. Its paper reports the best
stereochemistry accuracy among the readers it compares (85.1% on USPTO stereo
cases vs. 69.0% for MolScribe). That is the gap Track 2 tests: MolScribe and
MolGlyph each read only about half of BioVista's chiral crops correctly
(benchmarks/results/willdaly/comparison.md).

MolSight isn't on PyPI, and it needs newer timm and albumentations than the
shared environment pins for MolScribe, so it runs in its own environment
(benchmarks/liba-jin/README.md). This module:

1. fetches MolSight's code at a pinned commit with a sparse git checkout into a
   cache folder outside the repo, leaving out the bundled Linux-only Indigo
   libraries (MolSight only uses them to render training images);
2. applies the team's MolScribe abbreviation fix to MolSight's copy of the same
   function (see patch_molsight);
3. builds the model the way MolSight's inference.py does and loads the weights
   from Hugging Face (Robert-zwr/MolSight).

Two checkpoints are supported (VARIANTS):

- extra:  pubchem_uspto_smiles_edges_30.pth (748 MB), the best overall model in
          MolSight's README (92.0% on USPTO) and the one its inference.py uses;
- stereo: stereo_grpo_10_2.pth (257 MB), the same model after GRPO with LoRA
          adapters on Stereo-200k, tuned for stereochemistry.

    from molsight_reader import load_reader
    reader = load_reader("extra", device="cpu")
    reader.predict([rgb_array, ...])  # [{"smiles", "confidence", "raw"}, ...]
"""

from __future__ import annotations

import importlib.metadata
import inspect
import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from huggingface_hub import hf_hub_download

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # shared code: readers.py (the Reader contract)
from readers import Reader  # noqa: E402

MOLSIGHT_URL = "https://github.com/hustvl/MolSight.git"
# Latest commit on 2026-10-13 ("Release inference demo", 2025-12-05).
MOLSIGHT_COMMIT = "86e979b2880a01cfede864312460272eb07f6886"
WEIGHTS_REPO = "Robert-zwr/MolSight"
SPARSE_PATTERNS = ["/molsight/", "!/molsight/indigo/lib/", "/vocab/", "/LICENSE"]
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "xn-molecular-extraction"

# variant -> (weights file, output heads to build, LoRA adapters in the decoder), as in MolSight's
# eval.sh (char,edges) and post_eval.sh (grpo with --lora)
VARIANTS = {
    "extra": ("pubchem_uspto_smiles_edges_30.pth", ["char", "edges"], False),
    "stereo": ("stereo_grpo_10_2.pth", ["grpo"], True),
}
INPUT_SIZE = 512
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)  # what get_transforms uses for the efficientvit encoder


def fetch_molsight(cache: Path = CACHE) -> Path:
    """Check out MolSight's code at MOLSIGHT_COMMIT (once) and return the checkout folder."""
    root = cache / f"molsight-{MOLSIGHT_COMMIT[:7]}"
    if (root / "molsight" / "model.py").exists():
        return root
    root.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)

    if not (root / ".git").exists():
        git("init", "-q")
        git("remote", "add", "origin", MOLSIGHT_URL)
    git("sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS)
    # A blob-less shallow fetch downloads only the files the sparse checkout keeps.
    git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", MOLSIGHT_COMMIT)
    git("checkout", "-q", "FETCH_HEAD")
    return root


def patch_molsight(chem) -> None:
    """Apply the team's MolScribe abbreviation fix to MolSight's copy of the same function.

    molsight/chemistry.py copies MolScribe's _expand_functional_group, which
    reads each bond's order *after* RWMol.RemoveBond has deleted it. The stale
    Bond can report order 0, so BOND_TYPES[0] raises KeyError and the molecule
    with the abbreviation (Ph, OMe, Boc, ...) is lost. benchmarks/readers.py
    (patch_molscribe) describes the bug; this is the same fix: read the orders
    before removing the bonds. Calling it again is a no-op.
    """
    if getattr(chem, "_xn_patched", False):
        return
    src = inspect.getsource(chem._expand_functional_group)
    old_1 = "adjacent_indices = [bond.GetOtherAtomIdx(i) for bond in bonds]"
    old_2 = ("for adjacent_atom, bond in zip(adjacent_atoms, bonds):\n"
             "                    adjacent_atom.SetNumRadicalElectrons(int(bond.GetBondTypeAsDouble()))")
    assert old_1 in src and old_2 in src, "MolSight source changed; re-check the patch"
    src = src.replace(old_1, old_1 + "\n                bond_orders = [int(b.GetBondTypeAsDouble()) for b in bonds]")
    src = src.replace(old_2, "for adjacent_atom, order in zip(adjacent_atoms, bond_orders):\n"
                             "                    adjacent_atom.SetNumRadicalElectrons(order)")
    exec(src, chem.__dict__)  # redefines _expand_functional_group inside molsight.chemistry
    chem._xn_patched = True


class MolSightReader:
    """MolSight plus its own SMILES post-processing: RGB crops in, canonical SMILES out."""

    def __init__(self, variant: str = "extra", device: str = "cpu", cache: Path = CACHE):
        if variant not in VARIANTS:
            raise ValueError(f"unknown MolSight variant {variant!r}; choose from {', '.join(VARIANTS)}")
        root = fetch_molsight(cache)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        # MolSight wraps two decoder helpers in @torch.compile. Compiling for CPU needs a C++ compiler,
        # which a stock Windows machine doesn't have, and inference gives the same output eagerly.
        # torch.compile checks this variable when the decorators run, so set it before the import.
        os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
        import albumentations as A
        import cv2
        import molsight.chemistry as chem
        from albumentations.pytorch import ToTensorV2
        from molsight.augment import CropWhite
        from molsight.model import MolsightModel
        from molsight.tokenizer import CharTokenizer

        patch_molsight(chem)
        self._chem = chem
        self.variant = variant
        self.weights, formats, lora = VARIANTS[variant]
        args = SimpleNamespace(
            encoder="efficientvit", use_checkpoint=False, embed_dim=512, dec_n_layer=6, dec_n_head=8,
            use_qknorm=True, use_swiglu=True, use_rmsnorm=True, lora=lora, regression=False,
            input_size=INPUT_SIZE, formats=formats, max_len=320, n_coord_bins=128,
            resume=True,  # build the encoder without downloading ImageNet weights; the checkpoint replaces them
        )
        model = MolsightModel(args, CharTokenizer(str(root / "vocab" / "vocab_chars.json")))
        # The checkpoints are training snapshots (weights plus optimizer state and settings), so they
        # need the full pickle loader. They come from the authors' Hugging Face repo.
        checkpoint = torch.load(hf_hub_download(WEIGHTS_REPO, self.weights), map_location="cpu", weights_only=False)
        state = {k.removeprefix("module."): v for k, v in checkpoint.get("model", checkpoint).items()}
        missing, _ = model.load_state_dict(state, strict=False)
        if missing:
            raise RuntimeError(f"{self.weights} lacks {len(missing)} weights this model needs, e.g. {missing[:3]}")
        self.device = torch.device(device)
        self.model = model.to(self.device).eval()
        # get_transforms(augment=False, rotate=False) from molsight/dataset.py, rebuilt here because
        # that module also imports the training-only Indigo renderer and Hugging Face datasets.
        self.transform = A.Compose([
            CropWhite(pad=5),
            A.LongestMaxSize(max_size=INPUT_SIZE),
            A.PadIfNeeded(min_height=INPUT_SIZE, min_width=INPUT_SIZE, border_mode=cv2.BORDER_CONSTANT,
                          fill=(255, 255, 255)),
            A.ToGray(p=1),
            A.Normalize(mean=MEAN, std=STD),
            ToTensorV2(),
        ])

    def predict_images(self, images: list[np.ndarray], batch_size: int = 16) -> list[dict]:
        """Read each RGB crop with greedy decoding. Returns SMILES, MolSight's raw string and a confidence per crop.

        The confidence is the geometric mean of the token probabilities (exp of
        MolSight's avg_logprob), the same quantity readers.py reports for
        MolScribe and MolGlyph.
        """
        out = []
        for start in range(0, len(images), batch_size):
            batch = torch.stack([self.transform(image=img)["image"] for img in images[start:start + batch_size]])
            with torch.no_grad():
                kv_cache, hooks = self.model.install_kv_cache_hooks()
                try:
                    preds, _ = self.model.generate(image=batch.to(self.device), kv_cache=kv_cache)
                finally:
                    for hook in hooks:
                        hook.remove()
            for raw, avg_logprob in zip(preds["smiles"], preds["avg_logprob"]):
                out.append({"smiles": self.to_smiles(raw), "raw": raw, "confidence": math.exp(float(avg_logprob))})
        return out

    def to_smiles(self, raw: str) -> str:
        """MolSight's own post-processing (as in its inference.py): R-group labels become `*` atoms and
        abbreviations are expanded. Returns '' when the result isn't a valid molecule."""
        from rdkit import Chem

        smiles, _, ok = self._chem._postprocess_smiles(raw)
        if not ok:
            return ""
        try:
            return Chem.CanonSmiles(smiles)
        except Exception:
            return ""


def load_reader(variant: str = "extra", device: str = "cpu", batch_size: int = 16) -> Reader:
    """MolSight behind the benchmarks/readers.py contract: predict(crops) -> [{smiles, confidence, raw}]."""
    model = MolSightReader(variant, device)

    def predict(crops: list[np.ndarray]) -> list[dict]:
        return [{"smiles": p["smiles"], "confidence": p["confidence"], "raw": p["raw"]}
                for p in model.predict_images(crops, batch_size)] if crops else []

    versions = {pkg: importlib.metadata.version(pkg) for pkg in ("torch", "timm", "albumentations", "rdkit")}
    versions["molsight_code"] = f"hustvl/MolSight {MOLSIGHT_COMMIT[:7]} (abbreviation fix applied)"
    versions["molsight_weights"] = f"{WEIGHTS_REPO} {model.weights}"
    return Reader(f"molsight-{variant}", predict, versions)
