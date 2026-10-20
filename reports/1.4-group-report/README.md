# XN 1.4 report assembly

Canvas: [Group Benchmark Report & Phase 2 Plan](https://northeastern.instructure.com/courses/257799/assignments/3528944).
One 8-10 page PDF/DOCX, due November 1, 2026, 11:59 PM ET. Final group filename:
`XNGroup1_1_4_GroupReport.pdf` (or `.docx`). This folder currently contains Will's
architecture and Phase 2 section draft, not the assembled group submission.

## Available now

- `Daly_1_4_Phase2Sections.docx`: editable draft of the architecture and Phase 2
  plan, with an owner-labeled diagram, disclosure and source notes.
- `content.json`: text used to generate those sections.
- `pipeline.svg`: editable diagram source; `pipeline.png` is its Word fallback.
- `build.cjs`: regenerates the Word draft and diagram from `content.json` with
  Node packages `docx` and `sharp` installed outside the repo. Run
  `NODE_PATH=<external-node_modules> node reports/1.4-group-report/build.cjs` from
  the repo root. No runtime packages were added to the shared Python environment.
- [Pipeline proposal](../../pipeline/README.md) and [field contract](../../pipeline/INTERFACES.md).
- [Current team results](../../benchmarks/results/comparison.md), all four members.

The former [check-in draft](../1.4-sponsor-checkin/README.md) remains source
material for conclusions/questions; it has not yet been updated to current results.

## What still needs people

| Item | Proposed owner | Team target |
|---|---|---|
| Confirm module ownership and interface boundaries | All four members | Review now; interface target Oct 25 |
| Sponsor paper and BioMiner/BioVista review paragraphs | Will | Oct 28 |
| DECIMER or MolGrapher review paragraph | Bijay | Oct 28 |
| MolSight review paragraph | Jin | Oct 28 |
| MolNexTR review paragraph | Peter | Oct 28 |
| Each module's input, output, main risk and example fixture | Its owner | Oct 28 |
| Comparative analysis, refreshed conclusions/questions and full assembly | Per #23, coordinated by Will | Oct 30 |
| Final comments | Everyone | Oct 31 |
| One group submission | Will, proposed in #4 | Nov 1 |

These are proposed team dates/roles from #4, #23, #89 and #90. Do not count an
assigned literature source as a member's completed contribution. The draft does
not replace each person's review or the complete group's contribution statement.

## Revision after the 1.3 reports (October 20, 2026)

Claude revised `content.json` after all four 1.3 reports were in the repo: a proposed
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
