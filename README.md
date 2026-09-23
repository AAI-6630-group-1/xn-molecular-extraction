# XN Project: Computer Vision for Molecular Data Extraction

AAI 6630 Applied Computer Vision (Fall 2026), XN Project Group 1, Northeastern University.

We are building a computer vision system that finds molecular structure drawings in PDFs of scientific papers and converts them to SMILES strings for drug discovery and materials science research. The hard part is that real papers mix molecule drawings with text, tables, reaction schemes, and chemical notation, which is much messier than the isolated molecule images used in published benchmarks.

**Project board:** https://github.com/orgs/AAI-6630-group-1/projects/1

## Deliverables

1. **Benchmark testing results:** evaluate recent ML tools (BioMiner / BioVista) on public datasets and on the internal dataset of papers from previous cohorts.
2. **Custom extraction code:** Python that extracts SMILES from PDF files, written with agentic AI tools (Claude + VS Code).

| Phase | Weeks | XN tasks |
|---|---|---|
| 1. Benchmarking & Project Setup | 1 to 6 (Sep 22 to Nov 2) | 1.1 Setup Proposal · 1.2 Benchmarking Code · 1.3 Individual Benchmark Report · 1.4 Group Check-in: Sponsor · 1.5 Combined Report & Benchmark Aggregation |
| 2. Pipeline Development | 7 to 12 (Nov 3 to Dec 14) | 2.1 Literature Review & Pipeline Design · 2.2 Pipeline Module Implementation · 2.3 Module Documentation & Tests · 2.4 Pipeline Integration & Report |
| 3. Final Deliverables & Reflection | 13 (Dec 15 to 20) | 3.1 Individual Final Report · 3.2 Project Presentation · 3.3 Individual Reflection |

Due dates and progress live on the project board: see the [Roadmap](https://github.com/orgs/AAI-6630-group-1/projects/1/views/3) and [Deliverables](https://github.com/orgs/AAI-6630-group-1/projects/1/views/4) views.

## Repository layout

This is a starting point; change it if the team agrees on something better ([#15](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/15)).

| Path | Contents |
|---|---|
| `benchmarks/` | Phase 1 benchmarking code (one folder per person) and shared results |
| `pipeline/` | Phase 2 extraction pipeline, one module per stage |
| `reports/` | Sources and figures for write-ups worth versioning |
| `data/` | Notes on where datasets live; the data itself stays out of git |

## Getting started

```bash
git clone https://github.com/AAI-6630-group-1/xn-molecular-extraction.git
cd xn-molecular-extraction
```

The Python environment is being decided in [#15](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/15); setup steps go here once it is. See [CONTRIBUTING.md](CONTRIBUTING.md) for how we use issues, branches, and the project board.

## People

- **Team:** [willdaly](https://github.com/willdaly), [liba-jin](https://github.com/liba-jin), [PeterAdr14](https://github.com/PeterAdr14), [ArkAngel101](https://github.com/ArkAngel101)
- **Instructors:** Navdeep Dhanjal and Dr. Anton Sinitskiy (course lead)
- **External sponsor:** Dr. Jianing Li, Purdue University

## References

- Sponsor paper: [bioRxiv 10.64898/2026.06.23.734132](https://www.biorxiv.org/content/10.64898/2026.06.23.734132v1.full), section "Computer vision for data mining on organic molecules"
- BioMiner and the BioVista benchmark: [paper](https://arxiv.org/abs/2604.21508), [code](https://github.com/jiaxianyan/BioMiner)
- Canvas: [XN Project Overview](https://northeastern.instructure.com/courses/257799/pages/xn-project-overview-2), [Course Schedule](https://northeastern.instructure.com/courses/257799/pages/course-schedule)
