"""MolGrapher (Morin et al., 2023) as an OCSR reader.

MolGrapher detects atoms, builds a graph and turns it into a SMILES. Per its README
(https://github.com/DS4SD/MolGrapher):

    from molgrapher.models.molgrapher_model import MolgrapherModel
    annotations = MolgrapherModel().predict_batch(list_of_images_or_paths)

and each annotation is a dict with `smi` (SMILES) and `conf` (confidence) plus `file-info`. Weights
download from Hugging Face (ds4sd/MolGrapher) on first use.

Checked on BioVista (README.md): predict_batch returned one annotation per crop. predict() still matches
annotations to crops by file name when `file-info` has one, then by order, and raises if neither works;
ocsr_run.py then retries crop by crop. MolgrapherModel takes no device argument in the README, so `device`
is ignored; it used the GPU on its own. It runs its default node classifier, `gc_no_stereo_model`,
which does not predict stereochemistry, so exact match on chiral crops is 0 by design.
"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _source_commit() -> str:
    """Commit of the MolGrapher checkout (MOLGRAPHER_SRC), if setup_env.sh cloned one."""
    src = os.environ.get("MOLGRAPHER_SRC")
    if not src:
        return "unknown (set MOLGRAPHER_SRC to the clone)"
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=src, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load(device: str = "cuda"):
    from molgrapher.models.molgrapher_model import MolgrapherModel

    # MolgrapherModel() deletes its visualization folder at start-up (args["clean"]). Parallel shards share
    # that folder, so a shard starting while another writes pictures crashed with "Directory not empty"
    # (job 11210471_1). The pictures aren't used by the benchmark, so skip that one delete.
    real_rmtree = shutil.rmtree
    shutil.rmtree = lambda path, *a, **k: None if "visualization" in str(path) else real_rmtree(path, *a, **k)
    try:
        model = MolgrapherModel()
    finally:
        shutil.rmtree = real_rmtree

    def predict(paths: list[Path]) -> list[dict]:
        # MolGrapher writes a *_preprocessed.png next to every image it reads (it polluted the shared BioVista
        # crops folder on 2026-10-18), so give it throwaway copies in a temporary folder, deleted afterwards.
        with tempfile.TemporaryDirectory() as tmp:
            copies = [Path(shutil.copy(p, Path(tmp) / p.name)) for p in paths]
            annotations = model.predict_batch([str(c) for c in copies])
        by_name = {Path(str(a.get("file-info", {}).get("filename", ""))).stem: a for a in annotations}
        if all(p.stem in by_name for p in paths):
            ordered = [by_name[p.stem] for p in paths]
        elif len(annotations) == len(paths):
            ordered = list(annotations)
        else:
            raise ValueError(f"MolGrapher returned {len(annotations)} annotations for {len(paths)} crops")
        return [{"smiles": a.get("smi") or "", "confidence": a.get("conf"), "raw": a.get("smi") or ""}
                for a in ordered]

    try:
        version = importlib.metadata.version("molgrapher")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return predict, {
        "molgrapher": version,
        "molgrapher_commit": _source_commit(),
        "molgrapher_weights": "ds4sd/MolGrapher (Hugging Face, downloaded on first use)",
    }
