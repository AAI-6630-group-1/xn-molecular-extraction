"""Build the tables for the 1.4 results sections from the committed score files.

Reads the summary CSVs that `benchmarks/score.py --all` writes and Peter's own
comparison.csv for the older OCSR sets, and writes `results_tables.json`, which
`build_results.cjs` turns into Word tables. No model is run.

Run from the repo root (CPU, about a second):
    uv run python reports/1.4-group-report/results_tables.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "benchmarks/results"
OUT = Path(__file__).with_name("results_tables.json")

# (label, member, run_id) for recognition on BioVista and Patent300 crops.
READERS = [
    ("MolGlyph (BioMiner's reader)", "Will", "2026-10-06_molglyph_biovista", "2026-10-06_molglyph_patent300"),
    ("MolScribe", "Will", "2026-10-06_molscribe_biovista", "2026-10-04_molscribe_patent300"),
    ("MolSight-extra", "Jin", "2026-10-13_molsight-extra_biovista", "2026-10-13_molsight-extra_patent300"),
    ("MolNexTR*", "Peter", "2026-10-15_molnextr_biovista", None),
    ("DECIMER 2.8.0", "Bijay", "2026-10-18_decimer_biovista", None),
    ("MolGrapher (no-stereo model)", "Bijay", "2026-10-19_molgrapher_biovista", None),
    ("DeepSeek-OCR-2", "Bijay", "2026-10-19_deepseek_ocr2_biovista", None),
]
# (label, member, run_id) for end-to-end runs on the six internal papers. The three
# reader runs share the same 233 MolDetV2 boxes, so only the reader differs.
SYSTEMS = [
    ("MolDetV2 + MolScribe", "Will", "2026-10-04_moldetv2-molscribe-pad0_internal"),
    ("MolDetV2 + MolSight", "Jin", "2026-10-13_moldetv2-molsight-extra-pad0_internal"),
    ("MolDetV2 + MolGlyph", "Will", "2026-10-06_moldetv2-molglyph-pad0_internal"),
    ("Full BioMiner", "Will", "2026-10-13_biominer_internal"),
]
PAPERS = [  # paper, what its drawings test (from the team's paper review, #16 and #67)
    ("1", "Single drawn drugs"),
    ("2", "Scaffold + drawn substituent table"),
    ("4", "PROTAC series built from drawn pieces"),
    ("6", "One molecule, missed by all"),
    ("16", "Macrocycles"),
    ("19", "Scaffold + R-groups as table text"),
]


def rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def pct(x) -> str:
    return f"{float(x) * 100:.1f}%"


def main() -> None:
    ocsr = rows(RESULTS / "summary_ocsr_biovista.csv")
    patent = {r["run_id"]: r for r in rows(RESULTS / "summary_ocsr_patent300.csv")
              if r.get("structure", "all") == "all"}

    def biovista(run_id: str, structure: str) -> str:
        # Test split only; MolNexTR's run is Peter's 1,000-crop sample, so its test rows are the 897 sampled test crops.
        for r in ocsr:
            if r["run_id"] == run_id and r["subset"] == "test" and r["structure"] == structure:
                return pct(r["accuracy"])
        raise KeyError((run_id, structure))

    recognition = [["Reader", "Run by", "BioVista, all", "No R-group", "Chiral", "Markush", "Patent300 crops"]]
    for label, member, bv, p3 in READERS:
        recognition.append([label, member, biovista(bv, "all"), biovista(bv, "full"), biovista(bv, "chiral"),
                            biovista(bv, "markush"), pct(patent[p3]["accuracy"]) if p3 else "not run"])

    # Peter's own scorer (not score.py) for the older sets; it does not equate `[1*]` with `*`.
    peter = {(r["dataset"], r["tool"]): r for r in rows(REPO / "benchmarks/petera/benchmark_1_results/comparison.csv")
             if r["category"] == "all"}
    older = [["Dataset", "Images", "MolGlyph", "MolNexTR"]]
    for name in ("clef", "uob", "uspto", "jpo"):
        glyph, nextr = peter[(name, "biominer_molglyph")], peter[(name, "molnextr")]
        older.append([name.upper(), glyph["n_scored"], pct(glyph["exact_match"]), pct(nextr["exact_match"])])

    summary = rows(RESULTS / "summary.csv")
    by_run = {(r["run_id"], r["paper_id"]): r for r in summary}
    internal = [["Paper", "Molecules", "What it tests", *[f"{s} ({m})" for s, m, _ in SYSTEMS]]]
    for paper, tests in PAPERS:
        n = by_run[(SYSTEMS[0][2], paper)]["n_gt"]
        cells = []
        for _, _, run in SYSTEMS:
            r = by_run[(run, paper)]
            cells.append(f"{r['tp']} ({int(float(r['precision']) * 100 + 0.5)}%)")
        internal.append([paper, n, tests, *cells])
    for agg, name in (("macro", "Equal-weight P / R"), ("pooled", "Pooled P / R")):
        internal.append([name, "", "", *[f"{pct(by_run[(run, agg)]['precision'])} / {pct(by_run[(run, agg)]['recall'])}"
                                         for _, _, run in SYSTEMS]])
    internal.append(["Found / unique SMILES out", "220", "", *[f"{by_run[(run, 'pooled')]['tp']} / {by_run[(run, 'pooled')]['n_output']}"
                                                            for _, _, run in SYSTEMS]])

    OUT.write_text(json.dumps({"recognition": recognition, "older": older,
                               "internal": internal}, indent=2) + "\n", encoding="utf-8")
    for table in (recognition, older, internal):
        for row in table:
            print(" | ".join(map(str, row)))
        print()


if __name__ == "__main__":
    main()
