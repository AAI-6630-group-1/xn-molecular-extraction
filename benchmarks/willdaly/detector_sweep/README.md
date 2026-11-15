# MolDetV2 detector checks (November 6, 2026)

Two questions for the front-end module (#47):

1. Does changing MolDetV2's input size, confidence cutoff, or tiling find more molecules on our six papers?
2. How well does MolDetV2 do on labeled journal pages? We had only measured patents.

**Short answer:** keep the current setting (960 px, conf 0.5). No setting added a molecule, and on labeled journal pages MolDetV2 found 96% of molecules. The failure worth fixing is two neighbouring molecules merged into one box.

## 1. Sweep on the six internal papers

Sizes 960 to 1920 px, 1600 px overlapping tiles, conf 0.5, 0.26, and 0.1. The baseline reproduced all 233 boxes in `2026-10-06_moldetv2-molglyph_internal`.

| Setting | Boxes gained | Molecules (of 220) | Molecules lost |
|---|---:|---:|---:|
| 960 px, conf 0.5 (current) | 0 | 64 | 0 |
| 960 px, conf 0.26 | 18 | 64 | 0 |
| 1280 px, conf 0.5 | 31 | 64 | 0 |
| 1600 px, conf 0.5 | 34 | 64 | 0 |
| 1920 px, conf 0.5 | 37 | 64 | 0 |
| 1600 px tiles, conf 0.5 | 85 | 64 | 0 |
| 1600 px tiles, conf 0.1 | 138 | 64 | 0 |

The settings gained 149 unique boxes in all. MolGlyph read 72 as R-group pieces and 71 as wrong molecules; 6 gave no output or several fragments. None matched a molecule the baseline missed.

- **Small drawings are missed at 960 px.** 25 substituent cells on page 5 of paper 2, about 55 px wide, are found at 1600 px with confidence 0.79 to 0.86 but not at 960 px and conf 0.5.
- **Those pieces don't help yet.** An answer-key-guided assembly bound (pairs, H caps, two-ended linkers) stays at 20 new molecules with or without the extra boxes. That bound is 3 higher than the 17 in `reports/1.4-group-report/assembly_example.txt`, whichever detector setting is used.
- **Tiling is not worth it.** Most of what it adds is cut-off drawings, protein diagrams, and cartoons.

This sweep can't show misses that no setting finds, and these six papers are a development set, so use it to diagnose, not to tune.

## 2. Labeled pages: MolDet-Bench-Doc

447 pages and 2,178 molecules with tight boxes ([UniParser/MolDet-Bench](https://huggingface.co/datasets/UniParser/MolDet-Bench), CC-BY-NC-SA-4.0, not committed). Ultralytics `val` reproduced the developers' mAP50 of 0.9936 at 960 px. mAP50-95 came out at 0.9371 against 0.9544 on their card.

At IoU 0.5, conf 0.5:

| Pages | Size | Molecules | Found | Recall | Precision |
|---|---:|---:|---:|---:|---:|
| Journal (19) | 960 px | 148 | 142 | 95.9% | 97.3% |
| Journal (19) | 1280 px | 148 | 141 | 95.3% | 95.9% |
| Journal (19) | 1600 px | 148 | 142 | 95.9% | 95.9% |
| Patent (428) | 960 px | 2,030 | 2,008 | 98.9% | 98.7% |
| Patent (428) | 1280 px | 2,030 | 2,011 | 99.1% | 98.5% |
| Patent (428) | 1600 px | 2,030 | 1,986 | 97.8% | 98.8% |

The 95% interval on journal recall is about 91% to 98%. All sizes and thresholds are in `scores.csv`.

**Read these with care:**

- **The journal split is approximate.** The dataset doesn't mark page type. The 19 pages were picked by eye from thumbnails, and only part of the largest (A4) group was reviewed, so a few journal pages may sit in the patent row. The list is in `bench_score.py`.
- **19 pages is a small sample**, and it holds no boxes under 4% of page width, so it can't test the paper 2 cells. Only 5 boxes in the whole set are that small.

**The six journal misses at 960 px:** a hydrogen-bonded base pair merged into one box (2, `doc_017`), cocaine inside a reaction scheme (1, `doc_396`), a malformed strip-shaped label (1, `doc_291`), and a crowded panel of small molecules with odd labels (2, `doc_397`). Two of the four extra boxes are a real molecule (MTBE), so both rates are probably slightly understated.

## Suggested next steps

- Keep 960 px, conf 0.5 as the default.
- Test ways to split merged boxes, since that is the real failure and the case we most need for figures with several compounds.
- Run BioVista's detection set (`doc/BioVista.zip`, 7.9 GB, 500 papers) for a larger journal sample. Its card warns of missing annotations.

## Run it

From the repo root, in order (about 10 minutes on an M1 Pro CPU, no GPU). `read_extra.py` needs MolGlyph's weights, and all of this needs the internal papers in `data/internal/`.

```bash
uv run python benchmarks/willdaly/detector_sweep/sweep.py
uv run python benchmarks/willdaly/detector_sweep/compare_boxes.py
uv run python benchmarks/willdaly/detector_sweep/read_extra.py
uv run python benchmarks/willdaly/detector_sweep/assembly_bound.py
uv run python benchmarks/willdaly/detector_sweep/bench_eval.py
uv run python benchmarks/willdaly/detector_sweep/bench_score.py
```

Outputs are in `benchmarks/results/willdaly/2026-11-06_detector-sweep_internal/` and `benchmarks/results/willdaly/2026-11-06_moldetv2_moldet-bench-doc/`. Neither folder has a `predictions.csv`, so `score.py --all` skips them. The contact sheet of gained boxes goes to `data/detector_sweep/`, which is gitignored because it shows crops from the papers.

Versions: ultralytics 8.4.165, torch 2.14.0, pymupdf 1.28.2, rdkit 2026.3.2, weights `moldet_v2_yolo11n_960_doc.pt`, MolGlyph at the commit in `benchmarks/molglyph.py`.

## AI use

Claude Code wrote these scripts, ran them on Will's laptop, reviewed the box crops and page thumbnails, chose the 19 journal pages, and wrote this README.
