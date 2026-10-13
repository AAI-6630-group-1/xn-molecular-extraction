# Track 2: MolSight on molecule crops

XN task 1.2 (benchmarking code) for liba-jin.

This folder benchmarks **MolSight** (Zhang et al., AAAI 2026), a recent optical chemical structure recognition (OCSR) model built to get stereochemistry right. It runs on the same crops that Will's MolScribe and MolGlyph runs used (#71), so the reader is the only thing that changes and the results go straight into the team's comparison table for 1.5.

**Why MolSight:** on BioVista, MolScribe and MolGlyph each read only about half of the chiral crops correctly. MolSight's paper reports 85.1% on USPTO stereo cases, against 69.0% for MolScribe. This benchmark checks whether that advantage holds on crops from real papers.

## What's here

| File | What it does | Runs in |
|---|---|---|
| `molsight_reader.py` | Loads MolSight (code at a pinned commit, weights from Hugging Face) behind the team's reader interface: `predict(crops)` returns `smiles`, `confidence` and `raw` per crop | MolSight env |
| `make_crops.py` | Writes the Patent300 ground-truth crops and the MolDetV2 crops of the six internal papers | shared env |
| `run_molsight.py` | Runs MolSight on one dataset and writes `predictions.csv` and `run.json` in the #14 results format | MolSight env |
| `compare.py` | Puts MolSight next to MolScribe and MolGlyph in `benchmarks/results/liba-jin/comparison.md` (and `.csv`) | shared env |
| `requirements-molsight.txt` | Pinned packages for the MolSight environment | |
| `reproduce.sh` | Every step below, in order | |

Each run is a folder in `benchmarks/results/liba-jin/<run_id>/` with `run.json` (settings, versions, command, hardware, runtime), `predictions.csv` (one row per crop), and the scorer's `scores.csv` and `matches.csv`.

## Setup

1. **Shared environment** (from the repository root): `uv sync`. On Windows 11 it installs cleanly and `uv run pytest benchmarks/tests` passes (28 tests).
2. **Data:** `uv run python benchmarks/willdaly/download_data.py` downloads BioVista's OCSR crops (61 MB) and Patent300 (151 MB). The six internal papers come from Canvas (Dataset 2.zip) and go in `data/internal/` (see `data/README.md`).
3. **MolSight environment:**

   ```bash
   uv venv benchmarks/liba-jin/.venv-molsight --python 3.11
   uv pip install --python benchmarks/liba-jin/.venv-molsight/Scripts/python.exe -r benchmarks/liba-jin/requirements-molsight.txt
   ```

   On macOS and Linux the Python is `benchmarks/liba-jin/.venv-molsight/bin/python`. MolSight needs newer `timm` and `albumentations` than the shared environment pins for MolScribe, so it gets its own environment, as `benchmarks/readers.py` suggests for tools with their own stack. The first run fetches MolSight's code (commit `86e979b`, into `~/.cache/xn-molecular-extraction/`) and its weights from Hugging Face (`Robert-zwr/MolSight`: 748 MB for `extra`, 257 MB for `stereo`).

4. **Optional, NVIDIA GPU:** swap in the CUDA build of PyTorch, then add `--device cuda --batch-size 32` to the runs below (each batch caches the image features of every crop, so 32 is about the limit for 8 GB). A laptop CPU reads about one crop per second; the GPU is much faster.

   ```bash
   uv pip install --python benchmarks/liba-jin/.venv-molsight/Scripts/python.exe torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu130 --reinstall-package torch --reinstall-package torchvision
   ```

## Run it

```bash
uv run python benchmarks/liba-jin/make_crops.py
PY=benchmarks/liba-jin/.venv-molsight/Scripts/python.exe
$PY benchmarks/liba-jin/run_molsight.py --dataset biovista --variant extra
$PY benchmarks/liba-jin/run_molsight.py --dataset patent300 --variant extra
$PY benchmarks/liba-jin/run_molsight.py --dataset internal --variant extra
uv run python benchmarks/score.py benchmarks/results/liba-jin/<run_id>
uv run python benchmarks/liba-jin/compare.py
```

Use `--variant stereo` for the stereo checkpoint and `--limit 50` for a quick check. Runs write as they go, so `--resume` continues an interrupted run. `bash benchmarks/liba-jin/reproduce.sh` does everything in one go.

**Datasets and crops**

| Dataset | Crops | Task and metrics |
|---|---|---|
| BioVista OCSR (BioMiner's benchmark) | 8,861 crops as distributed; the headline is the test split (8,006) | `ocsr`: exact match, stereo-blind match, Tanimoto, BioVista's own match rule; broken down into full, chiral and Markush structures |
| Patent300 | 2,482 ground-truth boxes, no margin | `ocsr` |
| Internal papers | 233 MolDetV2 boxes at 300 dpi, no margin. All 233 box ids match Will's pad-0 runs | `e2e`: precision, recall and F1 per paper |

**MolSight checkpoints**

- `extra`: `pubchem_uspto_smiles_edges_30.pth`, the best overall model in MolSight's README (92.0% on USPTO) and the one its demo uses.
- `stereo`: `stereo_grpo_10_2.pth`, the same model after reinforcement learning (GRPO, with LoRA adapters) on 200k stereoisomers.

## Results

Exact match of canonical SMILES. MolScribe and MolGlyph are Will's runs from #71 on the same crops. The full table, with stereo-blind accuracy, Tanimoto similarity and BioVista's own match rule, is in [`benchmarks/results/liba-jin/comparison.md`](../results/liba-jin/comparison.md).

| Setting | MolScribe | MolGlyph | MolSight-extra | MolSight-stereo |
|---|---|---|---|---|
| BioVista test split, all (8,006 crops) | 46.4% | **78.0%** | 45.3% | 39.7% |
| ... full structures (4,410) | 68.6% | **74.8%** | 64.8% | 57.1% |
| ... chiral (2,056) | 48.7% | **50.8%** | 41.1% | 32.9% |
| ... chiral, ignoring stereo labels | 57.4% | **77.7%** | 56.4% | 51.4% |
| ... Markush (3,596) | 19.1% | **82.0%** | 21.3% | 18.4% |
| Patent300 ground-truth crops (2,482) | 78.3% | **78.6%** | 70.9% | 67.8% |
| Internal papers: molecules found (of 220) | 54 | **64** | 61 | 54 |
| Internal papers: macro F1 | 0.301 | **0.360** | 0.341 | 0.287 |

What the numbers say:

- **MolSight's stereo advantage didn't carry over to crops from real papers.** On BioVista's chiral crops, MolSight-extra read 41.1% exactly, below MolScribe (48.7%) and MolGlyph (50.8%). The stereo checkpoint did worse (32.9%).
- **Many of its chiral misses are only the stereo labels.** Ignoring stereo, MolSight-extra gets 56.4% of the chiral crops, so for about 15% of them it read the structure right but the wedges wrong.
- **Overall, MolSight-extra is close to MolScribe** on BioVista (45.3% vs. 46.4%) and below it on patents (70.9% vs. 78.3%). MolGlyph stays the best reader on journal crops, mostly because of Markush structures (82.0% vs. about 20% for the others).
- **On the six internal papers,** MolSight-extra found 61 of the 220 molecules, between MolScribe (54) and MolGlyph (64).
- **The stereo checkpoint scored lower than `extra` on every dataset.**

## Implementation notes

- **Same inputs, same scorer.** BioVista crops are read as distributed, Patent300 crops are the ground-truth boxes, and the internal crops are the same MolDetV2 boxes as Will's pad-0 runs. Every run is scored by `benchmarks/score.py` with RDKit 2026.3.2.
- **Abbreviation fix.** MolSight copies MolScribe's `_expand_functional_group`, which has the bug `patch_molscribe()` in `benchmarks/readers.py` fixes (it reads bond orders after deleting the bonds). `patch_molsight()` applies the same fix.
- **No `torch.compile`.** MolSight wraps two decoder functions in `@torch.compile`. On a Windows CPU that needs a C++ compiler, so the reader turns compiling off; the output is the same.
- **No Indigo libraries.** MolSight bundles Linux-only Indigo libraries that it only uses to render training images, so the checkout leaves them out.
- **Confidence** is the geometric mean of the token probabilities, the same quantity `readers.py` reports for MolScribe and MolGlyph. An empty `smiles` means MolSight's output didn't parse into a valid molecule (MolGlyph's convention); the untouched output is in `raw`.
- **Hardware:** Intel Core Ultra 9 185H, 32 GB RAM, Windows 11. The committed runs used the GPU (NVIDIA RTX 4060 Laptop, 8 GB, PyTorch 2.14.1+cu130): about 0.15 s per crop, 21 to 25 minutes for BioVista. On the CPU it's about 1 s per crop. Each `run.json` records the exact hardware and runtime.
- **CPU and GPU agree.** On the first 192 BioVista crops, the CPU and GPU runs gave the same SMILES for 191 crops with `extra` and 189 with `stereo`. The few differences are crops where MolSight is unsure, and tiny numerical differences change one step of the greedy decoding.

## Use of AI tools

Claude Code wrote and ran this code. I read it and checked the outputs before opening the pull request.
