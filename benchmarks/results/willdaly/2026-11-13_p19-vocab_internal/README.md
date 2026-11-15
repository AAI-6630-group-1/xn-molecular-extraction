# Paper 19 with the extended substituent vocabulary (2026-11-13)

Same run as `../2026-11-13_p19-assembly_internal` (same front end and readings),
with assembly and export rerun after adding paper 19's Table 6 spellings to
`pipeline/substituents.py` (17 spellings plus the `nC<n>H<2n+1>` straight-chain rule).

| Run | Output | Correct | Precision | Recall | Rows assembled |
|---|---|---|---|---|---|
| Before (`2026-11-13_p19-assembly_internal`) | 23 | 20 | 87.0% | 19.2% | 1 of 95 |
| This run | 40 | 37 | 92.5% | 35.6% | 18 of 95 |

All 18 assembled rows of Table 6 match the answer key. 12l (`-ethylphenyl`)
abstains on purpose: the spelling could mean phenethyl or 4-ethylphenyl. The
spellings were written from the chemistry and then checked against the answer
key, so on this paper they are tuned to the development benchmark.

Reproduce: run the steps in `../2026-11-13_p19-assembly_internal/README.md`.
