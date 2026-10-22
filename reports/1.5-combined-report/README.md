> **Superseded (2026-10-20):** Prof. Dhanjal combined 1.5 into the assignment posted as 1.4 (Group Benchmark Report & Phase 2 Plan, due Sun Nov 1), together with 2.1. The group report is assembled in [`../1.4-group-report/`](../1.4-group-report/) under #4 and #23. This outline is kept as source material for the results and comparative-analysis sections.

# 1.5 Combined report: outline (draft)

XN Project Group 1 · outline of 2026-10-13 for #23 · due Sun Nov 1 (tentative)

**Status:** the 1.5 assignment isn't on Canvas yet; the Course Schedule lists it as "Combined Report Contribution (G)". This outline mirrors the five sections of the individual 1.3 report, which 1.5 combines. Replace it with the Canvas structure when the page is posted. Every table and figure comes from the repo, so the report updates when a run is added.

## What each of us commits first

Your benchmark shows up in the shared tables only when it's in the repo in the shared format:

1. Run folders in `benchmarks/results/<handle>/<run_id>/` with `predictions.csv` and `run.json` ([format](../../benchmarks/README.md#save-each-run-in-its-own-folder)).
2. `uv run python benchmarks/score.py --all`, then `uv run python benchmarks/aggregate.py`. Your runs appear in [`benchmarks/results/comparison.md`](../../benchmarks/results/comparison.md).
3. To appear in the public-vs-internal table, add your system to `SYSTEMS` at the top of `benchmarks/aggregate.py`.
4. Your 1.3 report in `reports/<handle>/`, so its findings can be quoted here.

## Proposed sections

| Section | Content | Source | Owner |
|---|---|---|---|
| 1. Introduction | The task (journal PDF to SMILES), why real papers are harder than benchmarks, the tools we chose and why | 1.1 proposals, sponsor paper | willdaly |
| 2. Methods | Shared scoring (exact canonical-SMILES match, RDKit 2026.3.2, macro and pooled, unique SMILES output); datasets: six internal papers, BioVista, Patent300, MolDet-Bench; each person's setup, one paragraph each | `benchmarks/README.md`, each run's `run.json` | everyone, own paragraph |
| 3. Results | Public vs internal table and figure; per-paper table; recognition, detection, and end-to-end tables | `benchmarks/results/comparison.md`, `reports/1.4-sponsor-checkin/public_vs_internal.png` | willdaly assembles |
| 4a. Analysis: finding molecules | MolDetV2 vs OpenCV on patent and journal pages | Peter's runs | PeterAdr14 |
| 4b. Analysis: reading molecules | MolScribe, MolGlyph, MolSight, MolGrapher, DECIMER, DeepSeek-OCR-2 on the same crops; stereo (Jin); Markush | Will's, Jin's and Bijay's runs | liba-jin, ArkAngel101, willdaly |
| 4c. Analysis: full systems | BioMiner vs reader-only pipelines; what the language-model step adds; the sponsor paper's 13/220 | `benchmarks/willdaly/README.md` | willdaly |
| 4d. Public benchmarks vs real papers | The gap, and why: R-group tables, labels, fragments | all of the above | willdaly drafts, everyone reviews |
| 5. Limitations and Phase 2 | Six papers; ground-truth quirks (tautomers, salts); GPU batch noise; runs from uncommitted code; what Phase 2 builds first (#74, #77) | `comparison.md` flags, #63, #74 | everyone |

Per-paper precision and recall go in tables, not bar charts, because the papers range from 1 to 104 molecules.

## Open before drafting

- [ ] Canvas posts the 1.5 page (length, format, file name)
- [ ] Teammates' runs committed and scored (#34-#36)
- [ ] Sponsor answers from the 1.4 check-in (#21), especially on scoring rules, which could change the headline numbers
