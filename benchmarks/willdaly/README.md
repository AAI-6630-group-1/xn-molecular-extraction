# Track 3: finding molecules in the PDF (willdaly)

Pipeline: PyMuPDF renders each page, MolDetV2 boxes the molecules, MolScribe reads each crop, RDKit canonicalizes. See [#13](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/13) for the track split.

## Environment

Track 3 uses the shared environment (`uv sync`; see [Getting started](../../README.md#getting-started)). It was tested on an M1 Pro Mac (macOS 26.5, CPU only) with Python 3.11.14.

Why Python 3.11: MolScribe needs `numpy<2`, and its OpenNMT-py 2.2.0 tokenizer (`pyonmttok`) only has Apple Silicon wheels for Python 3.10 and 3.11. MolScribe is installed from GitHub because the PyPI release (1.1.1) pins `torch<2.0`, which has no Python 3.11 build for Apple Silicon.

## Weights

Downloaded from Hugging Face on first run into the Hugging Face cache, outside the repo:

| File | Size | License |
|---|---|---|
| `UniParser/MolDetv2` `moldet_v2_yolo11n_960_doc.pt` | 5.5 MB | CC BY-NC-SA 4.0 (non-commercial) |
| `yujieq/MolScribe` `swin_base_char_aux_1m.pth` | 1.1 GB | MIT |
| Docling layout model (heron), fetched by Docling | 172 MB | Apache-2.0 |

Ultralytics and PyMuPDF are AGPL-3.0. Importing Ultralytics writes a settings file to `~/Library/Application Support/Ultralytics/`.

## Smoke test

Needs the internal dataset in `data/internal/` (see [data/README.md](../../data/README.md)) and `benchmarks/score.py` from [#65](https://github.com/AAI-6630-group-1/xn-molecular-extraction/pull/65).

```bash
uv run python benchmarks/willdaly/smoke_test_track3.py --paper 16 --device cpu
```

It writes crops, `detections.csv`, and `summary.json` to `data/smoke_track3/` (gitignored, because the crops come from the papers).

Result on 2026-09-29, paper 16 (13 pages, 4 ground-truth molecules): 19 s wall clock on CPU (CPU was faster than MPS for MolScribe). MolDetV2 found 8 boxes, including all 4 molecules. MolScribe matched 0 of 4 exactly: parts of the drawings are in faint color, which it dropped or misread, and some outputs picked up stray fragments from nearby labels.

## MolScribe bug and patch

MolScribe returns `<invalid>` for every drawing that contains an abbreviation (Ph, OMe, Boc, ...). `_expand_functional_group` in `molscribe/chemistry.py` reads each bond's order after `RWMol.RemoveBond` has deleted the bond, and RDKit then reports the order as 0, so the lookup raises a `KeyError` that MolScribe catches silently. `patch_molscribe()` in `smoke_test_track3.py` reads the orders before removing the bonds. Call it before using MolScribe anywhere in this project.
