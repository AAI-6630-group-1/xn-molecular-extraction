# Data

Datasets stay out of git: everything in this folder except this README is ignored. Keep the files in the team's shared storage and record them here.

| Dataset | Where it lives | Ground truth | Restrictions |
|---|---|---|---|
| Internal papers (IDs 1, 2, 4, 6, 16, 19) | [Dataset 2.zip](https://northeastern.instructure.com/courses/257799/files/44295732) in the Canvas XN Project module | `ground_truth_SMILES_confirmed_1,2,4,6,16,19.csv`, in the same zip | Course use only. Papers 1, 2, and 6 are CC BY-NC-ND 4.0, so don't post them anywhere public |
| Public benchmarks | TBD ([#17](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/17)) | | |

## Internal papers

The six open-access papers the sponsor paper hand-curated as its benchmark. Use the article numbers as `paper_id` everywhere, gaps included (the instructor asked us to keep them).

Download Dataset 2.zip from Canvas and unzip it into `data/internal/` in your clone, so everyone's scripts can use the same paths:

```
data/internal/
├── 1.pdf, 2.pdf, 4.pdf, 6.pdf, 16.pdf, 19.pdf
└── ground_truth_SMILES_confirmed_1,2,4,6,16,19.csv
```

| ID | Paper | Source | License | Molecules |
|---|---|---|---|---|
| 1 | Cellular Context Influences Kinase Inhibitor Selectivity | [J. Med. Chem. 2026](https://doi.org/10.1021/acs.jmedchem.5c02916) | CC BY-NC-ND 4.0 | 17 |
| 2 | Development of a Chemical Probe to Enable Characterization of the Casein Kinase 1γ Subfamily | [J. Med. Chem. 2026](https://doi.org/10.1021/acs.jmedchem.5c02609) | CC BY-NC-ND 4.0 | 34 |
| 4 | Unhooking the Hook: Optimization of the Aurora A Targeting PROTAC JB170 to CCT400028 | [J. Med. Chem. 2026](https://doi.org/10.1021/acs.jmedchem.5c03024) | CC BY 4.0 | 61 |
| 6 | Proof-of-concept of targeted degradation of p38α/β MAPK host-kinase as a potent inhibitor of coronaviruses | [bioRxiv preprint 2026](https://doi.org/10.64898/2026.04.29.721712) | CC BY-NC-ND 4.0 | 1 |
| 16 | Enhancing the Predictive Power of Macrocyclic Drug Permeability by Knowledge Distillation from Analogous Pretraining Data | [J. Med. Chem. 2026](https://doi.org/10.1021/acs.jmedchem.5c02620) | CC BY 4.0 | 4 |
| 19 | Darizmetinib (HRX215): A Promising 1st-in-Class Liver Regenerating Drug in Phase 1b/2a Clinical Development, Targeting the Stress Signaling Protein Kinase MKK4 | [J. Med. Chem. 2026](https://doi.org/10.1021/acs.jmedchem.6c00689) | CC BY 4.0 | 105 |

The ground-truth CSV has 222 rows with the columns `paperID`, `name of molecule`, and `canonical_SMILES`. Before scoring against it, read the quirks in [#63](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/63#issuecomment-5803166763): two molecules are listed twice under different labels, five SMILES contain `*` placeholders for R-groups, and both sides should be re-canonicalized with the same RDKit version.
