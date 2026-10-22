# XN Project: Computer Vision for Molecular Data Extraction

AAI 6630 Applied Computer Vision (Fall 2026), XN Project Group 1, Northeastern University.

We are building a computer vision system that finds molecular structure drawings in PDFs of scientific papers and converts them to SMILES strings for drug discovery and materials science research. The hard part is that real papers mix molecule drawings with text, tables, reaction schemes, and chemical notation, which is much messier than the isolated molecule images used in published benchmarks.

**Project board:** https://github.com/orgs/AAI-6630-group-1/projects/1

## Deliverables

1. **Benchmark testing results:** evaluate recent ML tools (BioMiner / BioVista) on public datasets and on the internal dataset of papers from previous cohorts.
2. **Custom extraction code:** Python that extracts SMILES from PDF files, written with agentic AI tools (Claude + VS Code).

| Phase | Weeks | XN tasks |
|---|---|---|
| 1. Benchmarking & Project Setup | 1 to 6 (Sep 22 to Nov 2) | 1.1 Setup Proposal · 1.2 Benchmarking Code · 1.3 Individual Benchmark Report · 1.4 Group Benchmark Report & Phase 2 Plan (combines the old 1.4, 1.5 and 2.1) |
| 2. Pipeline Development | 7 to 12 (Nov 3 to Dec 14) | 2.2 Pipeline Module Implementation · 2.3 Module Documentation & Tests · 2.4 Pipeline Integration & Report |
| 3. Final Deliverables & Reflection | 13 (Dec 15 to 20) | 3.1 Individual Final Report · 3.2 Project Presentation · 3.3 Individual Reflection |

Due dates and progress live on the project board: see the [Roadmap](https://github.com/orgs/AAI-6630-group-1/projects/1/views/3) and [Deliverables](https://github.com/orgs/AAI-6630-group-1/projects/1/views/4) views.

## Repository layout

Propose changes to the layout in a pull request.

| Path | Contents |
|---|---|
| `benchmarks/` | Phase 1 benchmarking code (one folder per person) and shared results |
| `pipeline/` | Phase 2 extraction pipeline, one module per stage |
| `reports/` | Individual reports in `reports/<handle>/`, plus group write-ups (1.4, 2.4) |
| `setup-proposals/` | Each person's 1.1 setup proposal, in `setup-proposals/<handle>/` |
| `data/` | Notes on where datasets live; the data itself stays out of git |
| `hpc/` | Scripts for running on Northeastern's Explorer cluster (GPU jobs) |

## Getting started

```bash
git clone https://github.com/AAI-6630-group-1/xn-molecular-extraction.git
cd xn-molecular-extraction
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then create the pinned environment. uv downloads Python 3.11 if you don't have it and installs exactly the versions in `uv.lock` into `.venv/`:

```bash
uv sync
```

`pyproject.toml` lists the direct dependencies and why each is pinned; `uv.lock` pins everything else, with entries for macOS, Linux, and Windows (tested on macOS so far). Without uv, `requirements.txt` holds the same pins for pip (`python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt`); it is generated with `uv export --format requirements-txt --no-hashes`, so regenerate it after `uv lock`. To change a version, edit `pyproject.toml`, run `uv lock`, and commit both files. The environment covers PDF parsing (PyMuPDF, Docling), molecule detection (MolDetV2 through Ultralytics), recognition (MolScribe), RDKit 2026.3.2 for scoring, and pytest. It runs on a CPU; a GPU is optional. Model weights download from Hugging Face on first use and stay outside the repo.

Then get the internal dataset (see [data/README.md](data/README.md)) and check the setup:

```bash
uv run pytest benchmarks/tests
```

If you use MolScribe, load it with `load_reader("molscribe")` from [`benchmarks/readers.py`](benchmarks/readers.py), or call that file's `patch_molscribe()` first (the bug is described [here](benchmarks/willdaly/README.md#molscribe-bug-and-patch)). DECIMER needs TensorFlow, so it gets its own environment.

To run on a GPU on Northeastern's Explorer cluster, see [hpc/README.md](hpc/README.md).

See [CONTRIBUTING.md](CONTRIBUTING.md) for how we use issues, branches, and the project board.

## Benchmark code (task 1.2)

Each person's benchmarking code lives in `benchmarks/<handle>/` with its own README; the scorers they share are in `benchmarks/`.

| Where | What it is |
|---|---|
| [`benchmarks/willdaly/`](benchmarks/willdaly/README.md) | Track 3: MolDetV2 finds molecules on rendered PDF pages, then MolScribe or MolGlyph (BioMiner's recognizer) reads each one. Benchmarked on the internal papers, MolMole Patent300, and BioVista. Start with its README; `reproduce.sh` runs everything in order |
| [`benchmarks/liba-jin/`](benchmarks/liba-jin/README.md) | Track 2: MolSight (AAAI 2026, built for stereochemistry) as a third reader on the same crops as MolScribe and MolGlyph: BioVista, Patent300 ground-truth crops, and MolDetV2 crops of the internal papers. Runs in its own environment; `reproduce.sh` runs everything in order |
| [`benchmarks/score.py`](benchmarks/score.py), [`score_boxes.py`](benchmarks/score_boxes.py), [`score_biovista.py`](benchmarks/score_biovista.py) | Shared scoring: exact match of canonical SMILES (RDKit 2026.3.2), precision and recall per paper, detection AP, Tanimoto similarity. Rules in [`benchmarks/README.md`](benchmarks/README.md) |
| [`benchmarks/results/<handle>/<run_id>/`](benchmarks/results/willdaly) | One folder per run: `run.json` (command, versions, hardware, runtime), `predictions.csv` (every output SMILES with its confidence), `scores.csv` and `matches.csv` (from the scorer) |
| [`benchmarks/tests/`](benchmarks/tests) | `uv run pytest benchmarks/tests` |

## People

- **Team:** [willdaly](https://github.com/willdaly), [liba-jin](https://github.com/liba-jin), [PeterAdr14](https://github.com/PeterAdr14), [ArkAngel101](https://github.com/ArkAngel101)
- **Instructors:** Navdeep Dhanjal and Dr. Anton Sinitskiy (course lead)
- **External sponsor:** Dr. Jianing Li, Purdue University

## References

- Sponsor paper: [bioRxiv 10.64898/2026.06.23.734132](https://www.biorxiv.org/content/10.64898/2026.06.23.734132v1.full), section "Computer vision for data mining on organic molecules"
- BioMiner and the BioVista benchmark: [paper](https://arxiv.org/abs/2604.21508), [code](https://github.com/jiaxianyan/BioMiner)
- Canvas: [XN Project Overview](https://northeastern.instructure.com/courses/257799/pages/xn-project-overview-2), [Course Schedule](https://northeastern.instructure.com/courses/257799/pages/course-schedule)
