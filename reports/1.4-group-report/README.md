# XN 1.4 report assembly

Canvas: [Group Benchmark Report & Phase 2 Plan](https://northeastern.instructure.com/courses/257799/assignments/3528944).
One 8-10 page PDF/DOCX, due November 1, 2026, 11:59 PM ET. Final group filename:
`XNGroup1_1_4_GroupReport.pdf` (or `.docx`).

## The group report

`XNGroup1_1_4_GroupReport.docx` is the one document we submit. It is generated,
so edit the text files, not the docx:

| File | Sections |
|---|---|
| `front_content.json` | title, team members and contributions, literature review, AI disclosure, references |
| `results_content.json` | aggregated results, comparative analysis, conclusions, sponsor questions |
| `results_tables.json` | Tables 1-3, written by `results_tables.py` from the committed score files |
| `phase2_content.json` | pipeline architecture and Phase 2 plan |

Bracketed text such as `[pending ...]` is a placeholder and shows highlighted in
the docx. Rebuild from the repo root (Node packages `docx` and `sharp` installed
outside the repo; no packages added to the Python environment):

```bash
uv run python reports/1.4-group-report/results_tables.py
NODE_PATH=<external-node_modules> node reports/1.4-group-report/build.cjs
```

`build.cjs` also redraws the diagram (`pipeline.svg`, with `pipeline.png` for Word).
Export the final PDF from Word. Sources: [pipeline proposal](../../pipeline/README.md),
[field contract](../../pipeline/INTERFACES.md), [team results](../../benchmarks/results/comparison.md).

## Status (October 28, 2026)

- Owners follow #76; nobody asked to swap by Oct 20, so they are final.
  Interface version 0.1 is adopted (no review comments by the Oct 25 target).
- One environment: MolGlyph reads, MolScribe is the second vote. MolSight and
  MolNexTR are out of the pipeline (`reader_overlap.py`, output in `reader_overlap.txt`).
- Will's module example: `assembly_example.py` (output in `assembly_example.txt`)
  joins MolGlyph's one-attachment fragments. 17 missed answer-key molecules are
  recoverable with perfect pairing (papers 4 and 19), out of 582 same-page joins;
  paper 2 is the abstention case.
- Still open: the literature review (#89), teammates' contribution sentences,
  and trimming to 10 pages.

Both scripts read committed predictions only (CPU, seconds):

```bash
uv run python reports/1.4-group-report/reader_overlap.py
uv run python reports/1.4-group-report/assembly_example.py
```

## Revision after the 1.3 reports (October 20, 2026)

Claude revised the Phase 2 text (now `phase2_content.json`) after all four 1.3 reports were in the repo: a proposed
starting reader policy (MolGlyph primary, agreement with MolScribe or MolSight as the
precision filter, MolSight's stereochemistry when the skeletons agree), the cross-member
evidence behind it, the separate-environment rationale, and evaluation notes (one
R-group label convention; stereo evaluated on BioVista's chiral crops because only 7
internal answer rows are chiral). The four reports are now cited, and so is the sponsor paper. The same policy is
in `pipeline/INTERFACES.md` as a proposal for Bijay's module. The draft renders at 5
pages including the figure, disclosure and references.

## Verification record

On October 20, 2026, Codex ran `uv sync --frozen`, then
`uv run pytest pipeline/tests benchmarks/tests -q`: **39 passed** (five
third-party SWIG deprecation warnings). The one-paper smoke command rendered all
25 pages of `data/internal/6.pdf` at 72 DPI, extracted native text, and wrote the
stage files to `data/pipeline_runs/2026-10-20_interface-smoke-paper6/`.
The run has no predictions and explicitly marks five model/export stages as
stubs. It is not a benchmark and is rejected by the existing scorer. Smoke
versions: Python 3.11.14 and PyMuPDF 1.28.2; the shared tests used pytest 9.1.1
and RDKit 2026.3.2. No GPU job or additional benchmark was run.

The Word draft was rendered with bundled LibreOffice and all four pages were
visually inspected. ZIP/XML integrity, required disclosure/text and the embedded
figure were also checked. The requested legacy `scripts/office/validate.py` was
not found in the installed skills; these structural and visual checks were used.

Owner confirmation, actual gate/reader/linker/assembler implementations, populated
module fixtures and full integration tests remain pending. The current tests
check rotated/cropped-page coordinates, output preservation, invalid identifiers,
error reporting and rejection of smoke runs by the scorer.

The Word draft should be reviewed and rewritten by Will and the group. Export
the eventual combined document to PDF from Word, not from this build process.
The sponsor paper (Gulluoglu et al., 2026) is now cited in the architecture and
evaluation paragraphs; its open full text is on PubMed Central
(https://pmc.ncbi.nlm.nih.gov/articles/PMC13345091/). The literature review itself
(#89) remains open. Sources used
here are the Canvas overview, current repo results and team planning issues.

## AI disclosure

AI tool(s) used: Codex. Purpose: pipeline design, code scaffolding and drafting
the architecture/Phase 2 sections. Specific contribution: Codex wrote the
interface proposal, smoke runner/tests, diagram and document build, and executed
the checks above. Human design approval, member contributions and prose review
remain pending. Existing benchmark data was not generated or rerun in this work.

Harmonize and Turnitin are in play; this is scaffolding to rewrite in your own
voice, not final submission text.
