#!/usr/bin/env python3
"""Team comparison of every scored run, for tasks 1.4 and 1.5 (#22).

    uv run python benchmarks/score.py --all     # rescore every run, refresh the summary files
    uv run python benchmarks/aggregate.py       # write benchmarks/results/comparison.md and .csv

Reads the summary files score.py writes (benchmarks/results/summary*.csv) and each run's run.json,
for every handle. For each (handle, tool, task, dataset) the latest run is used; run IDs start
with the date. comparison.md has:

- Public benchmarks vs the internal papers: one row per system (SYSTEMS below), its scores on
  BioVista and Patent300 beside its score on the six internal papers. This is the comparison the
  revised 1.4 asks for.
- End to end on the internal papers: every run, per paper, with the number of SMILES output so a
  flood of false positives shows.
- Recognition on given crops, detection, and detection plus recognition on Patent300.
- The runs used, with what each one did and flags for anything that makes it not comparable:
  a run that covers only some papers, a different RDKit version, a different number of crops.

To add your tool to the first table, add it to SYSTEMS. The other tables pick up every run.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
PAPERS = ["1", "2", "4", "6", "16", "19"]
BIOVISTA_TEST_CROPS = 8006

# System -> {(task, dataset): tool}. Each reader is listed at the crop margin chosen for it on
# Patent300 (MolScribe no margin, MolGlyph 10 px), so the internal papers stay a clean test.
SYSTEMS = {
    "MolDetV2 + MolScribe (patched)": {
        ("ocsr", "biovista"): "molscribe",
        ("ocsr", "patent300"): "molscribe",
        ("e2e", "patent300"): "moldetv2-molscribe-pad0",
        ("e2e", "internal"): "moldetv2-molscribe-pad0",
    },
    "MolDetV2 + MolGlyph": {
        ("ocsr", "biovista"): "molglyph",
        ("ocsr", "patent300"): "molglyph",
        ("e2e", "patent300"): "moldetv2-molglyph",
        ("e2e", "internal"): "moldetv2-molglyph",
    },
    "MolDetV2 + MolSight-extra": {
        ("ocsr", "biovista"): "molsight-extra",
        ("ocsr", "patent300"): "molsight-extra",
        ("e2e", "internal"): "moldetv2-molsight-extra-pad0",
    },
    "DECIMER 2.8.0": {
        ("ocsr", "biovista"): "decimer",
    },
    "MolGrapher (no-stereo model)": {
        ("ocsr", "biovista"): "molgrapher",
    },
    "DeepSeek-OCR-2 (SMILES prompt)": {
        ("ocsr", "biovista"): "deepseek_ocr2",
    },
    "BioMiner, full (MinerU + MolDetV2 + MolGlyph + BioMiner-Instruct)": {
        ("e2e", "internal"): "biominer",
    },
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run_meta(results: Path, handle: str, run_id: str) -> dict:
    path = results / handle / run_id / "run.json"
    return json.loads(path.read_text()) if path.exists() else {}


def latest(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group summary rows by (handle, tool) and keep only each pair's latest run."""
    newest: dict[tuple[str, str], str] = {}
    for r in rows:
        key = (r["handle"], r["tool"])
        newest[key] = max(newest.get(key, ""), r["run_id"])
    out: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if newest[(r["handle"], r["tool"])] == r["run_id"]:
            out.setdefault((r["handle"], r["tool"]), []).append(r)
    return out


def pct(value: str | float | None) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value) * 100:.1f}%"


def internal_flags(rows: list[dict], meta: dict, usual_rdkit: str) -> list[str]:
    """Reasons an internal-paper run isn't directly comparable with the others."""
    flags = []
    counts = meta.get("counts") or {}
    if counts and set(counts) != set(PAPERS):
        flags.append(f"covers papers {', '.join(sorted(counts, key=int))} only")
    rdkit = {r.get("rdkit_version") for r in rows} - {"", None}
    if rdkit and rdkit != {usual_rdkit}:
        flags.append(f"scored with RDKit {', '.join(sorted(rdkit))}")
    return flags


def e2e_internal_table(groups: dict, results: Path) -> tuple[list[str], list[dict]]:
    """Markdown rows for every internal-paper run, plus a flat record per run."""
    usual = Counter(r.get("rdkit_version") for rows in groups.values() for r in rows).most_common(1)[0][0]
    head = ("| Run | " + " | ".join(f"Paper {p}" for p in PAPERS)
            + " | Found / 220 | Unique SMILES out | Invalid | Macro P | Macro R | Macro F1 | Pooled P | Pooled R | Flags |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    records = []
    ordered = sorted(groups.items(), key=lambda kv: -int(next(r for r in kv[1] if r["paper_id"] == "pooled")["tp"]))
    for (handle, tool), rows in ordered:
        by_paper = {r["paper_id"]: r for r in rows}
        macro, pooled = by_paper["macro"], by_paper["pooled"]
        meta = run_meta(results, handle, rows[0]["run_id"])
        flags = internal_flags(rows, meta, usual)
        cells = [f"{by_paper[p]['tp']}/{by_paper[p]['n_gt']}" if p in by_paper else "" for p in PAPERS]
        link = f"[{handle} / {tool}]({handle}/{rows[0]['run_id']})"
        lines.append(f"| {link} | " + " | ".join(cells) + f" | {pooled['tp']} | {pooled['n_output']} | {pooled['n_invalid']} | "
                     f"{pct(macro['precision'])} | {pct(macro['recall'])} | {pct(macro['f1'])} | {pct(pooled['precision'])} | "
                     f"{pct(pooled['recall'])} | {'; '.join(flags)} |")
        records.append({"handle": handle, "tool": tool, "run_id": rows[0]["run_id"], "found": pooled["tp"],
                        "n_output": pooled["n_output"], "macro_precision": macro["precision"], "macro_recall": macro["recall"],
                        "pooled_precision": pooled["precision"], "pooled_recall": pooled["recall"], "flags": "; ".join(flags)})
    return lines, records


def find(groups: dict, tool: str, select=lambda r: True) -> dict | None:
    """The latest row of a tool's run (any handle) that matches select."""
    for (_, t), rows in groups.items():
        if t == tool:
            match = [r for r in rows if select(r)]
            if match:
                return match[0]
    return None


def systems_table(summaries: dict) -> tuple[list[str], list[dict]]:
    """One row per system: public-benchmark scores beside internal-paper scores."""
    columns = [
        ("BioVista test, all crops (accuracy)", ("ocsr", "biovista"), lambda r: r["subset"] == "test" and r["structure"] == "all", "accuracy"),
        ("BioVista test, Markush (accuracy)", ("ocsr", "biovista"), lambda r: r["subset"] == "test" and r["structure"] == "markush", "accuracy"),
        ("Patent300 given crops (accuracy)", ("ocsr", "patent300"), lambda r: True, "accuracy"),
        ("Patent300 pages (F1)", ("e2e", "patent300"), lambda r: True, "f1"),
        ("Internal papers (pooled recall)", ("e2e", "internal"), lambda r: r["paper_id"] == "pooled", "recall"),
        ("Internal papers (pooled precision)", ("e2e", "internal"), lambda r: r["paper_id"] == "pooled", "precision"),
    ]
    head = "| System | " + " | ".join(c[0] for c in columns) + " |"
    lines = [head, "|" + "---|" * (len(columns) + 1)]
    records = []
    for system, tools in SYSTEMS.items():
        record = {"system": system}
        cells = []
        for label, key, select, metric in columns:
            row = find(summaries.get(key, {}), tools[key], select) if key in tools else None
            record[label] = row[metric] if row else ""
            cells.append(pct(row[metric]) if row else "not run")
        lines.append(f"| {system} | " + " | ".join(cells) + " |")
        records.append(record)
    return lines, records


def biovista_table(groups: dict) -> list[str]:
    structures = ["all", "full", "chiral", "markush"]
    lines = ["| Tool | Crops scored | " + " | ".join(f"{s} (accuracy)" for s in structures) + " | Stereo-blind (all) | Tanimoto (all) | Flags |",
             "|" + "---|" * (len(structures) + 5)]
    for (handle, tool), rows in sorted(groups.items()):
        test = {r["structure"]: r for r in rows if r["subset"] == "test"}
        if "all" not in test:
            continue
        flags = [] if int(test["all"]["n_gt"]) == BIOVISTA_TEST_CROPS else [f"{test['all']['n_gt']} of {BIOVISTA_TEST_CROPS} test crops"]
        lines.append(f"| {handle} / {tool} | {int(test['all']['n_gt']):,} | " + " | ".join(pct(test[s]["accuracy"]) if s in test else "" for s in structures)
                     + f" | {pct(test['all']['accuracy_stereo_blind'])} | {float(test['all']['mean_tanimoto']):.3f} | {'; '.join(flags)} |")
    return lines


def simple_table(groups: dict, columns: list[tuple[str, str, str]]) -> list[str]:
    """One row per run; columns are (header, field, format) with format 'pct', 'num' or 'int'."""
    fmt = {"pct": pct, "num": lambda v: f"{float(v):.3f}", "int": lambda v: f"{int(v):,}"}
    lines = ["| Tool | " + " | ".join(c[0] for c in columns) + " |", "|" + "---|" * (len(columns) + 1)]
    for (handle, tool), rows in sorted(groups.items()):
        r = rows[0]
        lines.append(f"| {handle} / {tool} | " + " | ".join(fmt[f](r[field]) if r.get(field) not in (None, "") else "" for _, field, f in columns) + " |")
    return lines


def runs_table(all_groups: list[dict], results: Path) -> list[str]:
    lines = ["| Run | Task, dataset | Pipeline | Hardware | Commit | Notes | Flags |", "|---|---|---|---|---|---|---|"]
    seen = set()
    for groups in all_groups:
        for (handle, tool), rows in sorted(groups.items()):
            run_id = rows[0]["run_id"]
            if run_id in seen:
                continue
            seen.add(run_id)
            meta = run_meta(results, handle, run_id)
            cell = lambda v: str(v or "").replace("|", "/").replace("\n", " ")
            commit = str(meta.get("git_commit") or "")
            flags = "run from uncommitted code" if commit.endswith("-dirty") else ""
            lines.append(f"| [{run_id}]({handle}/{run_id}) | {meta.get('task', '')}, {meta.get('dataset', '')} | {cell(meta.get('pipeline'))} | "
                         f"{cell(meta.get('hardware'))} | {cell(commit)} | {cell(meta.get('notes'))} | {flags} |")
    return lines


def main(results: Path = RESULTS) -> int:
    summaries = {
        ("e2e", "internal"): latest(read_csv(results / "summary.csv")),
        ("ocsr", "biovista"): latest(read_csv(results / "summary_ocsr_biovista.csv")),
        ("ocsr", "patent300"): latest(read_csv(results / "summary_ocsr_patent300.csv")),
        ("e2e", "patent300"): latest(read_csv(results / "summary_e2e_patent300.csv")),
        ("detect", "patent300"): latest(read_csv(results / "summary_detect_patent300.csv")),
    }
    if not summaries[("e2e", "internal")]:
        print(f"no runs in {results / 'summary.csv'}; run `uv run python benchmarks/score.py --all` first", file=sys.stderr)
        return 1
    handles = sorted({h for groups in summaries.values() for (h, _) in groups})
    systems_lines, systems_records = systems_table(summaries)
    internal_lines, _ = e2e_internal_table(summaries[("e2e", "internal")], results)

    md = [
        "# Team benchmark comparison",
        "",
        f"Generated by `benchmarks/aggregate.py` on {date.today().isoformat()} from the summary files `benchmarks/score.py --all` writes, "
        f"using each handle's latest run of each tool. Handles with scored runs: {', '.join(handles)}. "
        "Exact match of canonical SMILES (RDKit) unless a column says otherwise. Per-paper results stay in tables because the papers "
        "range from 1 to 104 molecules.",
        "",
        "## Public benchmarks vs the internal papers",
        "",
        "Each system's score on clean public benchmarks beside its score on the six internal papers (220 molecules), the comparison "
        "the revised 1.4 asks for. The public columns score recognition on given crops (BioVista, Patent300) or whole patent pages "
        "(Patent300 F1); the internal columns score whole journal PDFs end to end. BioMiner's reader is MolGlyph, so its "
        "recognition scores are the MolGlyph row's.",
        "",
        *systems_lines,
        "",
        "## End to end on the six internal papers",
        "",
        "Molecules found out of each paper's total, sorted by the number found. *Unique SMILES out* counts distinct canonical "
        "SMILES, so a run that outputs many wrong structures shows it. Macro averages the six papers equally; pooled counts every "
        "molecule once.",
        "",
        *internal_lines,
        "",
        "## Recognition on given crops",
        "",
        "BioVista's OCSR test split (8,006 crops from journal figures), by structure type:",
        "",
        *biovista_table(summaries[("ocsr", "biovista")]),
        "",
        "Patent300's ground-truth crops (2,482 molecules on 300 patent pages):",
        "",
        *simple_table(summaries[("ocsr", "patent300")], [("Crops", "n_gt", "int"), ("Accuracy", "accuracy", "pct"),
                                                         ("Stereo-blind", "accuracy_stereo_blind", "pct"), ("Tanimoto", "mean_tanimoto", "num")]),
        "",
        "## Detection on Patent300",
        "",
        *simple_table(summaries[("detect", "patent300")], [("COCO AP", "ap", "num"), ("COCO AR", "ar", "num"), ("AP at IoU 0.5", "ap50", "num"),
                                                           ("Precision at IoU 0.5", "precision50", "pct"), ("Recall at IoU 0.5", "recall50", "pct")]),
        "",
        "## Detection and recognition on Patent300 pages",
        "",
        *simple_table(summaries[("e2e", "patent300")], [("Predicted", "n_pred", "int"), ("Correct", "tp", "int"), ("Precision", "precision", "pct"),
                                                        ("Recall", "recall", "pct"), ("F1", "f1", "pct")]),
        "",
        "## Runs used",
        "",
        *runs_table(list(summaries.values()), results),
        "",
    ]
    (results / "comparison.md").write_text("\n".join(md))
    with open(results / "comparison.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(systems_records[0]))
        writer.writeheader()
        writer.writerows(systems_records)
    print(f"wrote {results / 'comparison.md'} and comparison.csv ({sum(len(g) for g in summaries.values())} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
