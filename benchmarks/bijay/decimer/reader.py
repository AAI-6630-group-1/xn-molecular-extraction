"""DECIMER Image Transformer (Rajan et al., 2023) as an OCSR reader.

DECIMER is TensorFlow, so it has its own environment (see setup_env.sh and requirements.txt) and
can't be loaded through benchmarks/readers.py. benchmarks/bijay/common/ocsr_run.py loads this file instead.

predict_SMILES(path, confidence=True) returns the SMILES and one (token, probability) pair per token.
`confidence` here is the geometric mean of those token probabilities, the same definition the team's
readers use (benchmarks/readers.py). DECIMER reads one crop at a time, so there is no batching.
Its weights download to ~/.data/DECIMER-V2 on first import; run one job (or setup_env.sh) first, so
parallel shards don't all download them at once.
"""

from __future__ import annotations

import importlib.metadata
import math
from pathlib import Path


def load(device: str = "cuda"):
    import tensorflow as tf
    if device == "cpu":
        tf.config.set_visible_devices([], "GPU")  # must happen before DECIMER builds its model
    from DECIMER import predict_SMILES

    def predict(paths: list[Path]) -> list[dict]:
        out = []
        for path in paths:
            smiles, tokens = predict_SMILES(str(path), confidence=True)
            probs = [float(p) for _, p in tokens]
            conf = math.exp(sum(math.log(max(p, 1e-12)) for p in probs) / len(probs)) if probs else 0.0
            out.append({"smiles": smiles, "confidence": conf, "raw": smiles})
        return out

    return predict, {
        "decimer": importlib.metadata.version("decimer"),
        "tensorflow": tf.__version__,
        "decimer_weights": "DECIMER-V2 (downloaded by the package to ~/.data/DECIMER-V2)",
        "gpus_visible": str(len(tf.config.list_physical_devices("GPU"))),
    }
