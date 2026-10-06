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

## Benchmark on the six internal papers (task 1.2)

```bash
uv run python benchmarks/willdaly/run_track3.py
uv run python benchmarks/score.py benchmarks/results/willdaly/<run_id>
uv run python benchmarks/willdaly/analyze_track3.py benchmarks/results/willdaly/<run_id>
```

`run_track3.py` renders every page, boxes molecules with MolDetV2, and reads every box with MolScribe. Every box's output counts as a prediction: there is no filter, no label linking, and no R-group enumeration yet. It writes `run.json` and `predictions.csv` to `benchmarks/results/willdaly/<run_id>/` and the crops to `data/track3_runs/<run_id>/` (gitignored). Each row's `box_id` names its crop. `analyze_track3.py` breaks a scored run down by error type. Runs are deterministic on CPU: rerunning the 300 dpi baseline gave identical predictions.

Results on 2026-10-04. A molecule counts only if its canonical SMILES matches the ground truth exactly:

| Run | Macro precision | Macro recall | Macro F1 | Pooled precision | Pooled recall | Correct | Runtime |
|---|---|---|---|---|---|---|---|
| [300 dpi](../results/willdaly/2026-10-04_moldetv2-molscribe_internal) (default) | 29.0% | 31.9% | 29.3% | 27.9% | 23.2% | 51 of 220 | 83 s |
| [200 dpi](../results/willdaly/2026-10-04_moldetv2-molscribe-200dpi_internal) | 20.2% | 18.8% | 19.0% | 23.4% | 19.6% | 43 of 220 | 82 s |
| [300 dpi, no margin](../results/willdaly/2026-10-04_moldetv2-molscribe-pad0_internal) | 31.2% | 30.5% | 30.1% | 30.5% | 24.5% | 54 of 220 | 72 s |

For reference, the sponsor paper's best pipeline (Docling figures, a molecule gate, MolScribe) reported roughly 11% precision and 21% recall on the same papers. Rendering at 300 dpi, the resolution the figures are embedded at, found more molecules than 200 dpi on four papers, tied on paper 6, and found one fewer on paper 19 (15 against 16).

The no-margin run uses the crop margin chosen on Patent300 (below), applied here without retuning. It found 3 more molecules overall: paper 1 went from 14 to 17 of 17 and paper 19 from 15 to 17, while paper 16 fell from 2 to 1 and paper 2 from 9 to 8. Because paper 16 has only 4 molecules, macro recall dropped slightly even though pooled recall rose.

Per paper at 300 dpi, with what each MolDetV2 box became:

| Paper | Molecules | Correct | Precision | Recall | Boxes | Invalid | R-group scaffold | Extra fragments | Wrong |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 17 | 14 | 77.8% | 82.4% | 18 | 0 | 0 | 4 | 0 |
| 2 | 34 | 9 | 25.7% | 26.5% | 74 | 1 | 2 | 6 | 54 |
| 4 | 60 | 11 | 15.9% | 18.3% | 77 | 12 | 17 | 5 | 32 |
| 6 | 1 | 0 | 0% | 0% | 2 | 0 | 0 | 0 | 2 |
| 16 | 4 | 2 | 25.0% | 50.0% | 8 | 3 | 0 | 2 | 1 |
| 19 | 104 | 15 | 29.4% | 14.4% | 54 | 7 | 13 | 16 | 3 |

What the misses are:

- **R-group tables.** Papers 2, 4 and 19 hold 198 of the 220 molecules and draw many of them as one scaffold plus a table of substituents. Paper 19 has 104 molecules but only 54 boxes, and 30 boxes in papers 4 and 19 came back as scaffolds with `*` atoms. On paper 2's page 5, MolDetV2 boxes each substituent cell, and MolScribe reads it as a standalone fragment (`[H]C(C)C` 20 times, `CC(C)N1CCOCC1` 10 times). 53 of paper 2's 54 wrong boxes are on that page. Getting these molecules needs scaffold-plus-table enumeration, which this pipeline doesn't do.
- **Stray fragments.** MolScribe picks up nearby label text as extra atoms (`CC.`, `.N`). Keeping only the largest fragment of each prediction would raise the correct count from 51 to 59. It would also strip salts the ground truth keeps (paper 4's compound 18 is an HCl salt), so it isn't applied by default.
- **Tautomers.** Two paper 2 misses are the right molecule with the benzimidazole NH drawn on the other nitrogen. Matching after RDKit's tautomer canonicalization finds 53; with largest-fragment cleanup as well, 63.
- **No stereo-only misses.** Stereo-blind recall equals exact recall, so wedge errors aren't costing anything yet.
- **Local labels.** Pooled recall on molecules with paper-local names (like `12a`) is 16.8%, against 82.4% on paper 1's named drugs, which are single drawings. The pipeline only reads drawings, so this gap reflects drawing difficulty, not name lookups.

## MolMole Patent300: detection and recognition scored separately

```bash
uv run python benchmarks/willdaly/run_patent300.py
uv run python benchmarks/score.py benchmarks/results/willdaly/<run_id>
```

[Patent300](../../data/README.md#molmole-patent300) has a ground-truth box and molfile for each of its 2,482 molecules, so each stage can be scored on its own (see [score_boxes.py](../score_boxes.py)). It is also where Track 3 settings get tuned, so the six internal papers stay a clean test. `run_patent300.py` writes three runs: MolDetV2 boxes (`detect`), MolScribe on the ground-truth crops (`ocsr`), and the two together (`e2e`). Results on 2026-10-04, next to what the MolMole paper reports for the same pages (LG AI Research, 2025, Tables 2 to 4):

| Stage | Metric | Ours | MolMole paper |
|---|---|---|---|
| [Detection](../results/willdaly/2026-10-04_moldetv2_patent300) | COCO AP / AR / F1 | MolDetV2: 0.938 / 0.949 / 0.943 | ViDetect 0.914 / 0.938 / 0.926; DECIMER Segmentation 0.891 / 0.930 / 0.910; MolDetect 0.796 / 0.841 / 0.818 |
| [Recognition, ground-truth crops](../results/willdaly/2026-10-04_molscribe_patent300) | Exact match / Tanimoto | MolScribe (patched): 0.783 / 0.891 | MolScribe 0.709 / 0.913; DECIMER 0.753 / 0.914; ViMore 0.900 / 0.957 |
| [Both, 10 px margin](../results/willdaly/2026-10-04_moldetv2-molscribe_patent300) | Precision / recall / F1 | MolDetV2 + MolScribe: 0.721 / 0.719 / 0.720 | MolDetect + MolScribe 0.693 / 0.682 / 0.688; DECIMER 0.738 / 0.737 / 0.738; ViDetect + ViMore 0.895 / 0.887 / 0.891 |
| [Both, no margin](../results/willdaly/2026-10-04_moldetv2-molscribe-pad0_patent300) | Precision / recall / F1 | MolDetV2 + MolScribe: 0.779 / 0.776 / 0.778 | |

On the M1 Pro's CPU, detection took 32 s and each recognition run 13 to 15 minutes.

- **Detection is close to solved on patents.** At score 0.5 and IoU 0.5, MolDetV2 finds 2,466 of 2,482 molecules with 7 extra boxes (precision 0.997, recall 0.994). Our COCO AP and AR match `pycocotools` to four decimals. MolDetV2 was trained on 60,000 annotated pages, patents included, and that set isn't published, so overlap with Patent300 can't be ruled out.
- **Recognition is the bottleneck.** MolScribe misreads 539 of the 2,482 ground-truth crops. Among them, 150 outputs are invalid, 109 contain `*` atoms the molecule doesn't have (an abbreviation it couldn't expand, or a chain cut off at the box edge), 105 contain stray extra fragments (`CC.`), and 33 differ only in stereo. These groups can overlap. Our exact-match rate is higher than MolMole's for MolScribe and our Tanimoto is lower. We run the patched MolScribe, and MolMole doesn't say which fingerprint it used, so treat the comparison as approximate.
- **Crop margin.** The detected boxes are about 1.5 px larger than the ground-truth boxes on each side. Adding 10 px more (the internal-paper default) costs 191 molecules and gains 48, compared with no margin. With no margin, end-to-end F1 (0.778) nearly matches recognition on the ground-truth crops (0.783).
- **Largest fragment.** On the ground-truth crops, keeping each prediction's largest fragment fixes 81 molecules and breaks 6, raising exact match from 78.3% to 81.3%. That makes it a candidate default chosen on Patent300 rather than on the test papers. On the internal papers it has to keep paper 4's HCl salt.

## MolScribe bug and patch

MolScribe returns `<invalid>` for every drawing that contains an abbreviation (Ph, OMe, Boc, ...). `_expand_functional_group` in `molscribe/chemistry.py` reads each bond's order after `RWMol.RemoveBond` has deleted the bond, and RDKit then reports the order as 0, so the lookup raises a `KeyError` that MolScribe catches silently. `patch_molscribe()` in `smoke_test_track3.py` reads the orders before removing the bonds. Call it before using MolScribe anywhere in this project.
