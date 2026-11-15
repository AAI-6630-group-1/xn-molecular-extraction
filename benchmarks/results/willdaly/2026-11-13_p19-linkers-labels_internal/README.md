# Paper 19 with linkers, star labels and ring atoms (2026-11-13)

Same front end and readings as `../2026-11-13_p19-assembly_internal`, with
assembly and export rerun after three additions to `pipeline/assembly.py`:
columns matched to scaffold stars by MolGlyph's drawn labels (`Ra` to `R[a]`),
two-point linkers (`SO2`, `CO`) and ring-atom columns (`-N=`, `-C(Cl)=`).

| Run | Output | Correct | Precision | Recall | Rows assembled |
|---|---|---|---|---|---|
| Phase 1 MolDetV2 + MolGlyph (`2026-10-06_moldetv2-molglyph_internal`) | 50 | 21 | 42.0% | 20.2% | none |
| Front end + assembly (`2026-11-13_p19-assembly_internal`) | 23 | 20 | 87.0% | 19.2% | 1 of 95 |
| + vocabulary (`2026-11-13_p19-vocab_internal`) | 40 | 37 | 92.5% | 35.6% | 18 of 95 |
| + linkers, labels, ring atoms (this run) | 62 | 59 | 95.2% | 56.7% | 43 of 95 |

The 43 assembled rows give 40 distinct molecules (vemurafenib appears in three
tables), and all 40 match the answer key. The 3 false positives are drawing
readings. The 52 rows that still abstain:

- 45 in activity tables (Tables 5, 8, 10, 12, 13) that list compounds drawn
  elsewhere and have no scaffold. These need label linking, not assembly.
- 5 on purpose: `CONH` and `NHCO` (orientation depends on the drawing),
  `CH=CH` and `(COH)-(COH)` (stereochemistry not given), `-ethylphenyl`
  (phenethyl or 4-ethylphenyl).
- 2 in Table 4, which has no R column.

The rules were written from the chemistry and the table conventions, then
checked against paper 19's answer key, so on this paper they are tuned to the
development benchmark. Reproduce with the steps in
`../2026-11-13_p19-assembly_internal/README.md`.
