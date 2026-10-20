"""DeepSeek-OCR-2 (3B vision-language model) asked to read a molecule drawing as a SMILES string.

Unlike DECIMER and MolGrapher this is a general document OCR model, not a chemistry model, so the
prompt matters and the output is free text. Per the model card (https://huggingface.co/deepseek-ai/DeepSeek-OCR-2):

    model = AutoModel.from_pretrained(name, _attn_implementation="flash_attention_2",
                                      trust_remote_code=True, use_safetensors=True).eval().cuda().to(torch.bfloat16)
    model.infer(tokenizer, prompt=..., image_file=..., output_path=..., base_size=1024, image_size=768, crop_mode=True)

It needs an NVIDIA GPU with bf16 and FlashAttention (the card tested CUDA 11.8, flash-attn 2.7.3), so ask
for an A100 or an H200, not a V100 (see run.sbatch).

The model card doesn't say what infer() returns. predict() uses the return value if it is a string,
otherwise reads the newest .mmd/.md/.txt file infer() wrote to a temporary folder. On BioVista the answer
came back as text wrapped in <smiles>...</smiles>, which clean() strips; `raw` keeps the answer as given.
Choices that affect the scores: the SMILES prompt below is mine, not the model card's, and was not tuned,
and crop_mode=False because a BioVista crop is one small drawing rather than a full page. The model gives
no confidence, so that column is empty.

trust_remote_code=True runs code from the Hugging Face repo. DEEPSEEK_OCR2_REVISION pins it to a commit; the
BioVista run left it unpinned (latest at the time), and run.json records that.
"""

from __future__ import annotations

import importlib.metadata
import os
import re
import tempfile
from pathlib import Path

MODEL = "deepseek-ai/DeepSeek-OCR-2"
PROMPT = "<image>\nConvert the chemical structure in this image to a SMILES string. Output only the SMILES. "


def clean(text: str) -> str:
    """First non-empty line of the model's answer, with its tags and code fences removed.

    The model wraps a structure as <smiles>...</smiles>; `raw` keeps the answer as the model gave it.
    """
    text = re.sub(r"<\|[^|]*\|>", " ", text)  # <|ref|>...<|/ref|>, <|det|> and similar tags
    text = re.sub(r"</?smiles>", " ", text, flags=re.IGNORECASE)
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        if line and not line.lower().startswith(("smiles", "```")):
            return line.replace(" ", "")
        if line.lower().startswith("smiles"):
            return line.split(":", 1)[-1].strip().replace(" ", "")
    return ""


def load(device: str = "cuda"):
    import torch
    from transformers import AutoModel, AutoTokenizer

    revision = os.environ.get("DEEPSEEK_OCR2_REVISION") or None
    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, revision=revision)
    model = AutoModel.from_pretrained(MODEL, _attn_implementation="flash_attention_2", trust_remote_code=True,
                                      use_safetensors=True, revision=revision)
    model = model.eval().cuda().to(torch.bfloat16)

    def predict(paths: list[Path]) -> list[dict]:
        out = []
        for path in paths:
            with tempfile.TemporaryDirectory() as tmp:
                res = model.infer(tokenizer, prompt=PROMPT, image_file=str(path), output_path=tmp,
                                  base_size=1024, image_size=768, crop_mode=False, save_results=True)
                if not isinstance(res, str):
                    written = sorted(Path(tmp).rglob("*"), key=lambda p: p.stat().st_mtime)
                    texts = [p for p in written if p.suffix in {".mmd", ".md", ".txt"}]
                    res = texts[-1].read_text(encoding="utf-8") if texts else ""
            out.append({"smiles": clean(res), "confidence": None, "raw": res})  # the model gives no confidence
        return out

    def version(pkg: str) -> str:
        try:
            return importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            return "not installed"

    return predict, {
        "model": MODEL, "model_revision": revision or "unpinned (latest)",
        "torch": torch.__version__, "transformers": version("transformers"), "flash_attn": version("flash-attn"),
        "prompt": PROMPT.strip(),
    }
