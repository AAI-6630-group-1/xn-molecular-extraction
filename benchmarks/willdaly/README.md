# Track 3: finding and reading molecules in PDFs (willdaly)

XN task 1.2 benchmarking code for Track 3 of [#13](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/13). It benchmarks the "find each molecule on the page, then read it" approach to turning journal PDFs into SMILES:

1. **Render** each PDF page with PyMuPDF (300 dpi).
2. **Detect** every molecule drawing with MolDetV2, a YOLO11 detector that BioMiner also uses.
3. **Recognize** each crop with one of two readers: **MolScribe**, the recognizer in the sponsor paper's pipeline, or **MolGlyph**, BioMiner's recognizer (BioMiner itself needs NVIDIA GPUs; MolGlyph runs on a laptop CPU).
4. **Score** the SMILES against ground truth with the team's shared scorers: exact match of RDKit canonical SMILES, plus Tanimoto similarity, detection AP, and per-paper precision and recall.

It runs on three datasets that go from clean to messy: **BioVista**'s 8,861 molecule crops (recognition only, the benchmark BioMiner was evaluated on), **MolMole Patent300**'s 300 patent pages (detection and recognition scored separately and together), and the course's **six internal papers** (PDF in, SMILES out). The side-by-side results are in [`comparison.md`](../results/willdaly/comparison.md); the [Results](#results) section below summarizes them.

## What's where

| File | Pipeline stage | What it does |
|---|---|---|
| [`download_data.py`](download_data.py) | data | Downloads Patent300 and BioVista into `data/` and checks the internal papers are there |
| [`run_track3.py`](run_track3.py) | render, detect, recognize | The six internal papers, PDF to SMILES (`--reader`, `--pad`, `--dpi`) |
| [`run_patent300.py`](run_patent300.py) | detect, recognize | Patent300: MolDetV2 boxes, the reader on ground-truth crops, and both together |
| [`run_biovista.py`](run_biovista.py) | recognize | BioVista's crops, one SMILES each; resumable |
| [`../readers.py`](../readers.py) | recognize | MolScribe and MolGlyph behind one `predict(crops)` interface, shared with the team |
| [`../molglyph.py`](../molglyph.py) | recognize | Loads BioMiner's MolGlyph from a pinned commit without installing BioMiner |
| [`smoke_test_track3.py`](smoke_test_track3.py) | all | One-paper smoke test; also holds `render()` |
| [`../score.py`](../score.py), [`../score_boxes.py`](../score_boxes.py), [`../score_biovista.py`](../score_biovista.py) | score | Shared scorers (rules in [`../README.md`](../README.md)) |
| [`analyze_track3.py`](analyze_track3.py) | analysis | Breaks an internal-paper run down by error type |
| [`compare.py`](compare.py) | analysis | Writes the MolScribe vs MolGlyph table, `comparison.md` and `comparison.csv` |
| [`reproduce.sh`](reproduce.sh) | all | Every step above, in order |
| [`../results/willdaly/<run_id>/`](../results/willdaly) | output | `run.json` (command, versions, git commit, hardware, runtime), `predictions.csv` (every SMILES with its confidence), `scores.csv`, `matches.csv` |
| [`../../reports/willdaly/figures_1_3.py`](../../reports/willdaly/figures_1_3.py) | report | Figures for the 1.3 report |

No path is hard-coded: every script finds the repository from its own location, data lives in the gitignored `data/` folder, and model weights download to the Hugging Face cache. Run IDs are `<date>_<tool>_<dataset>`.

## Setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone the repo, and run `uv sync` in it. That installs Python 3.11 and the exact versions in `uv.lock` (for pip, use `requirements.txt`; see the [top-level README](../../README.md#getting-started)).
2. Check the install: `uv run pytest benchmarks/tests`.
3. Put the internal papers in `data/internal/`: download "Dataset 2.zip" from the Canvas XN Project module and unzip it there ([data/README.md](../../data/README.md)). It needs a course login, so no script can fetch it.
4. `uv run python benchmarks/willdaly/download_data.py` downloads Patent300 (151 MB) and BioVista's OCSR set (61 MB).
5. MolGlyph's weights are gated: open [jiaxianustc/MolGlyph](https://huggingface.co/jiaxianustc/MolGlyph), accept the terms while logged in to Hugging Face, then run `uv run hf auth login`. The other weights (MolDetV2 5.5 MB, MolScribe 1.1 GB, MolGlyph 1.7 GB) download on first use.

No GPU is needed; everything here ran on an M1 Pro's CPU.

## Running the benchmarks

`bash benchmarks/willdaly/reproduce.sh` runs every step in order (about 4.5 hours on the M1 Pro's CPU, most of it BioVista). Each step can also run on its own:

```bash
uv run python benchmarks/willdaly/run_track3.py --reader molscribe --pad 0 --tool moldetv2-molscribe-pad0   # ~1.5 min
uv run python benchmarks/willdaly/run_biovista.py --reader molglyph                                         # ~65 min
uv run python benchmarks/score.py --all                       # scores every run under benchmarks/results/
uv run python benchmarks/willdaly/compare.py                  # side-by-side table
uv run python benchmarks/willdaly/analyze_track3.py benchmarks/results/willdaly/<run_id>   # error breakdown
```

Each run writes `run.json` and `predictions.csv` to `benchmarks/results/willdaly/<run_id>/`, and crops from the internal papers to `data/track3_runs/<run_id>/` (gitignored, since they come from the papers). `predictions.csv` keeps every output, including invalid ones, with the reader's confidence (the geometric mean of its token probabilities) and, for BioVista, the raw output before post-processing.

## Results

Every number below is exact match of RDKit canonical SMILES unless it says otherwise, and comes from a committed `scores.csv`. The full side-by-side table is [`comparison.md`](../results/willdaly/comparison.md) ([CSV](../results/willdaly/comparison.csv)). Each reader uses the crop margin Patent300 chose for it: none for MolScribe, 10 px for MolGlyph.

| Stage and data | Metric | MolScribe | MolGlyph | Published |
|---|---|---|---|---|
| Detection, Patent300 (2,482 molecules) | COCO AP; recall / precision at IoU 0.5 | MolDetV2: 0.938; 99.4% / 99.7% | same detector | MolMole's best AP 0.914 |
| Recognition, Patent300 ground-truth crops | Exact (Tanimoto) | 78.3% (0.891) | 78.6% (0.926) | MolScribe 70.9% (MolMole) |
| Recognition, BioVista test split (8,006 crops) | Exact | 46.4% | **78.0%** | 45.5% / 76.4% (BioMiner, its own rule) |
| ... full structures (4,410) | Exact | 68.6% | 74.8% | 70.3% / 75.8% |
| ... with stereocentres (2,056) | Exact | 48.7% | 50.8% | 48.1% / 50.4% |
| ... Markush, R-group `*` (3,596) | Exact | 19.1% | **82.0%** | 15.6% / 77.0% |
| Detection + recognition, Patent300 | F1 | 77.8% | 79.2% | MolDetect + MolScribe 68.8% (MolMole) |
| PDF to SMILES, six internal papers | Macro precision / recall | 31.2% / 30.5% | **37.6% / 37.2%** | Sponsor paper's Claude Code run: 13 of 220 found |
| | Found / unique SMILES output | 54 / 177 | 64 / 164 | |

What the results say, in short (the 1.3 report has the full interpretation):

- **Detection isn't the bottleneck once it runs on whole pages.** With the same recognizer, this pipeline finds four times as many internal-paper molecules as the sponsor paper's Docling-plus-gate pipeline.
- **The setup reproduces BioMiner's published numbers.** Scored with BioVista's own match rule (`accuracy_biovista`), MolScribe gets 44.7% and MolGlyph 75.9% on the test split, within 1.3 points of BioMiner's table in every structure group.
- **Markush structures separate the readers.** MolScribe reads a substituent's attachment point as a carbon: 1,426 of its 2,908 BioVista Markush misses (49%) are otherwise exact. MolGlyph keeps it as `*`.
- **R-group tables cap recall on the internal papers.** MolGlyph turns 143 of the 233 boxes into Markush pieces (a scaffold or substituent with `*`), which can't match the ground truth's complete molecules until something enumerates the tables. Even pooling both readers finds only 66 of 220.
- **Two cheap filters.** Keeping only SMILES both readers agree on raises internal-paper precision from 39% to 69% (pooled) and loses 12 molecules; on BioVista, agreed answers are 92% correct. MolScribe's confidence ranks right above wrong with AUROC 0.87 on the internal boxes, 0.85 on BioVista, and 0.72 on Patent300 crops; MolGlyph's is 0.80 on the internal boxes and 0.78 on BioVista.

### BioVista: recognition on 8,861 crops

```bash
uv run python benchmarks/willdaly/run_biovista.py --reader molscribe     # 45 min
uv run python benchmarks/willdaly/run_biovista.py --reader molglyph      # 46 min
uv run python benchmarks/score.py benchmarks/results/willdaly/2026-10-06_molscribe_biovista benchmarks/results/willdaly/2026-10-06_molglyph_biovista
```

Runs: [MolScribe](../results/willdaly/2026-10-06_molscribe_biovista), [MolGlyph](../results/willdaly/2026-10-06_molglyph_biovista). Test split; "BioVista rule" is `accuracy_biovista`, which BioMiner's published table uses.

| Structures | Crops | MolScribe exact | MolGlyph exact | MolScribe, BioVista rule | MolGlyph, BioVista rule | Published (MolScribe / MolGlyph) |
|---|---|---|---|---|---|---|
| All | 8,006 | 46.4% | 78.0% | 44.7% | 75.9% | 45.5% / 76.4% |
| Full | 4,410 | 68.6% | 74.8% | 69.1% | 75.1% | 70.3% / 75.8% |
| Chiral | 2,056 | 48.7% | 50.8% | 47.8% | 49.8% | 48.1% / 50.4% |
| Markush | 3,596 | 19.1% | 82.0% | 14.9% | 76.9% | 15.6% / 77.0% |

- MolGlyph is right on 2,931 crops MolScribe misses, and MolScribe on 398 that MolGlyph misses; either one is right on 83.0%.
- MolGlyph's biggest error class is stereochemistry: 652 of its 1,759 misses are right apart from wedges, and its chiral accuracy rises from 50.8% to 77.7% if stereo is ignored.
- MolScribe always returns a string, and 305 of its test-split outputs don't parse (`<invalid>` or broken SMILES). MolGlyph's post-processing drops captions that don't parse, so it gave no output for 87 crops instead.
- Some labels are wrong: a spot check of paper 51_6rrm found three selenium compounds labelled with `*` in place of Se.

## Environment

Track 3 uses the shared environment (`uv sync`; see [Getting started](../../README.md#getting-started)). It was tested on an M1 Pro Mac (macOS 26.5, CPU only) with Python 3.11.14.

Why Python 3.11: MolScribe needs `numpy<2`, and its OpenNMT-py 2.2.0 tokenizer (`pyonmttok`) only has Apple Silicon wheels for Python 3.10 and 3.11. MolScribe is installed from GitHub because the PyPI release (1.1.1) pins `torch<2.0`, which has no Python 3.11 build for Apple Silicon.

MolGlyph needs nothing extra. Its code is BioMiner's fork of MolScribe, which uses the same pinned libraries; [`molglyph.py`](../molglyph.py) checks out only that folder of [jiaxianyan/BioMiner](https://github.com/jiaxianyan/BioMiner) at commit `17c6161` into `~/.cache/xn-molecular-extraction/` (62 files) and imports it as `biominer_molscribe`, so it can't shadow the installed MolScribe.

## Weights

Downloaded from Hugging Face on first run into the Hugging Face cache, outside the repo:

| File | Size | License |
|---|---|---|
| `UniParser/MolDetv2` `moldet_v2_yolo11n_960_doc.pt` | 5.5 MB | CC BY-NC-SA 4.0 (non-commercial) |
| `yujieq/MolScribe` `swin_base_char_aux_1m.pth` | 1.1 GB | MIT |
| `jiaxianustc/MolGlyph` `molglyph_large.pt` (gated: accept the terms on Hugging Face first) | 1.7 GB | MIT |
| Docling layout model (heron), fetched by Docling | 172 MB | Apache-2.0 |

Ultralytics and PyMuPDF are AGPL-3.0. Importing Ultralytics writes a settings file to `~/Library/Application Support/Ultralytics/`.

## Smoke test

Needs the internal dataset in `data/internal/` (see [data/README.md](../../data/README.md)) and `benchmarks/score.py` from [#65](https://github.com/AAI-6630-group-1/xn-molecular-extraction/pull/65).

```bash
uv run python benchmarks/willdaly/smoke_test_track3.py --paper 16 --device cpu
```

It writes crops, `detections.csv`, and `summary.json` to `data/smoke_track3/` (gitignored, because the crops come from the papers).

Result on 2026-09-29, paper 16 (13 pages, 4 ground-truth molecules): 19 s wall clock on CPU (CPU was faster than MPS for MolScribe). MolDetV2 found 8 boxes, including all 4 molecules. MolScribe matched 0 of 4 exactly: parts of the drawings are in faint color, which it dropped or misread, and some outputs picked up stray fragments from nearby labels.

## Results in detail: the six internal papers

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
| [MolGlyph, 10 px margin](../results/willdaly/2026-10-06_moldetv2-molglyph_internal) | 37.6% | 37.2% | 36.0% | 39.0% | 29.1% | 64 of 220 | 90 s |
| [MolGlyph, no margin](../results/willdaly/2026-10-06_moldetv2-molglyph-pad0_internal) | 37.6% | 37.0% | 36.0% | 39.0% | 29.1% | 64 of 220 | 88 s |

For reference, the sponsor paper's best pipeline (Docling figures, a molecule gate, MolScribe, run by Claude Code) found 13 of the 220 molecules, from 54 valid SMILES. It reports roughly 11% precision and 21% recall, but its Table 3 appears to swap the two columns for that run (paper 1's 9 correct of 11 outputs is printed as 52.9% precision). Rendering at 300 dpi, the resolution the figures are embedded at, found more molecules than 200 dpi on four papers, tied on paper 6, and found one fewer on paper 19 (15 against 16).

The no-margin run uses the crop margin chosen on Patent300 (below), applied here without retuning. It found 3 more molecules overall: paper 1 went from 14 to 17 of 17 and paper 19 from 15 to 17, while paper 16 fell from 2 to 1 and paper 2 from 9 to 8. Because paper 16 has only 4 molecules, macro recall dropped slightly even though pooled recall rose.

MolGlyph found the same 64 molecules with either margin, so the choice made on Patent300 (10 px, F1 0.792 against 0.788) doesn't matter here. It found 10 more than MolScribe with its own best margin: 2 more in paper 2, 3 in paper 4, 1 in paper 16, and 4 in paper 19. Per paper (each reader with its Patent300 margin):

| Paper | Molecules | MolScribe found / output | MolGlyph found / output |
|---|---|---|---|
| 1 | 17 | 17 / 17 | 17 / 17 |
| 2 | 34 | 8 / 31 | 10 / 29 |
| 4 | 60 | 11 / 67 | 14 / 58 |
| 6 | 1 | 0 / 2 | 0 / 2 |
| 16 | 4 | 1 / 8 | 2 / 8 |
| 19 | 104 | 17 / 52 | 21 / 50 |

What each MolDetV2 box became (`analyze_track3.py`): of 233 boxes, MolScribe gave 57 correct, 37 R-group scaffolds, 23 with extra fragments, 15 invalid, and 101 other wrong molecules; MolGlyph gave 68 correct, 143 Markush pieces, 1 with extra fragments, 4 empty, and 17 other wrong molecules. The difference is mostly paper 2's table of substituents, which MolScribe reads as 57 whole (wrong) molecules and MolGlyph as 58 substituents with an attachment point. [Figure 2 of the 1.3 report](../../reports/willdaly/figures/fig2_box_outcomes.png) draws this per paper.

Per paper for the first baseline (MolScribe, 300 dpi, 10 px margin), with what each MolDetV2 box became:

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

## Results in detail: MolMole Patent300

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
| [Recognition, ground-truth crops](../results/willdaly/2026-10-06_molglyph_patent300) | Exact match / Tanimoto | MolGlyph: 0.786 / 0.926 | |
| [Both, 10 px margin](../results/willdaly/2026-10-06_moldetv2-molglyph_patent300) | Precision / recall / F1 | MolDetV2 + MolGlyph: 0.793 / 0.790 / 0.792 | |
| [Both, no margin](../results/willdaly/2026-10-06_moldetv2-molglyph-pad0_patent300) | Precision / recall / F1 | MolDetV2 + MolGlyph: 0.790 / 0.787 / 0.788 | |

On the M1 Pro's CPU, detection took 32 s and each recognition run 13 to 19 minutes. On patents the two readers tie on exact match (78.3% and 78.6%), MolGlyph's near misses are nearer (Tanimoto 0.926 against 0.891), and a 10 px margin barely moves MolGlyph while it costs MolScribe 5.8 F1 points.

- **Detection is close to solved on patents.** At score 0.5 and IoU 0.5, MolDetV2 finds 2,466 of 2,482 molecules with 7 extra boxes (precision 0.997, recall 0.994). Our COCO AP and AR match `pycocotools` to four decimals. MolDetV2 was trained on 60,000 annotated pages, patents included, and that set isn't published, so overlap with Patent300 can't be ruled out.
- **Recognition is the bottleneck.** MolScribe misreads 539 of the 2,482 ground-truth crops. Among them, 150 outputs are invalid, 109 contain `*` atoms the molecule doesn't have (an abbreviation it couldn't expand, or a chain cut off at the box edge), 105 contain stray extra fragments (`CC.`), and 33 differ only in stereo. These groups can overlap. Our exact-match rate is higher than MolMole's for MolScribe and our Tanimoto is lower. We run the patched MolScribe, and MolMole doesn't say which fingerprint it used, so treat the comparison as approximate.
- **Crop margin.** The detected boxes are about 1.5 px larger than the ground-truth boxes on each side. Adding 10 px more (the internal-paper default) costs 191 molecules and gains 48, compared with no margin. With no margin, end-to-end F1 (0.778) nearly matches recognition on the ground-truth crops (0.783).
- **Largest fragment.** On the ground-truth crops, keeping each prediction's largest fragment fixes 81 molecules and breaks 6, raising exact match from 78.3% to 81.3%. That makes it a candidate default chosen on Patent300 rather than on the test papers. On the internal papers it has to keep paper 4's HCl salt.

## MolScribe bug and patch

MolScribe returns `<invalid>` for every drawing that contains an abbreviation (Ph, OMe, Boc, ...). `_expand_functional_group` in `molscribe/chemistry.py` reads each bond's order after `RWMol.RemoveBond` has deleted the bond, and RDKit then reports the order as 0, so the lookup raises a `KeyError` that MolScribe catches silently. `patch_molscribe()` in [`../readers.py`](../readers.py) reads the orders before removing the bonds. `load_reader("molscribe")` applies it; call it yourself before using MolScribe any other way in this project.

## How this code was written

The course expects agentic AI for the project code, so this says which parts it wrote. Claude Code (Anthropic) wrote the Track 3 code in this folder and the shared scorers and readers in `benchmarks/` at Will's direction, ran every benchmark on Will's laptop, and drafted this README. Will chose the tools, datasets, and metrics (1.1 proposal and #14), approved each dataset and weight download, and reviews and merges every pull request. The checks behind the numbers: `pytest benchmarks/tests` (28 tests), a fresh-environment install from `requirements.txt`, the refactored runners reproducing the committed MolScribe predictions exactly, and both readers reproducing BioMiner's published BioVista accuracies within 1.3 points.
