#!/usr/bin/env python3
"""Put MolSight next to MolScribe and MolGlyph on the same crops: comparison.md and comparison.csv.

Reads the scores.csv that benchmarks/score.py wrote for each run: Will's
MolScribe and MolGlyph runs (benchmarks/results/willdaly/, from #71) and the
MolSight runs in benchmarks/results/liba-jin/. When a MolSight setting has
several runs (say a --limit check and the full run), the one with the most
crops wins, then the newest.

    uv run python benchmarks/liba-jin/compare.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RESULTS = REPO / "benchmarks" / "results"
OUT = RESULTS / "liba-jin"

# Will's runs on the same crops (#71): reader -> run_id per dataset
WILL = {
    "MolScribe": {"biovista": "2026-10-06_molscribe_biovista", "patent300": "2026-10-04_molscribe_patent300",
                  "internal": "2026-10-04_moldetv2-molscribe-pad0_internal"},
    "MolGlyph": {"biovista": "2026-10-06_molglyph_biovista", "patent300": "2026-10-06_molglyph_patent300",
                 "internal": "2026-10-06_moldetv2-molglyph-pad0_internal"},
}
VARIANTS = {"extra": "MolSight-extra", "stereo": "MolSight-stereo"}


def read_scores(run_dir: Path) -> list[dict]:
    path = run_dir / "scores.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def molsight_runs() -> dict[str, dict[str, Path]]:
    """Reader name -> dataset -> run folder, for the scored MolSight runs."""
    best: dict[tuple[str, str], tuple[int, str, Path]] = {}
    for run_json in OUT.glob("*/run.json"):
        run = json.loads(run_json.read_text())
        variant = run.get("settings", {}).get("variant")
        if variant not in VARIANTS or not (run_json.parent / "scores.csv").exists():
            continue
        key = (VARIANTS[variant], run["dataset"])
        rank = (run["settings"].get("n_crops", 0), run_json.parent.name, run_json.parent)
        if key not in best or rank[:2] > best[key][:2]:
            best[key] = rank
    out: dict[str, dict[str, Path]] = {}
    for (reader, dataset), (_, _, path) in best.items():
        out.setdefault(reader, {})[dataset] = path
    return out


def pick(rows: list[dict], **match) -> dict | None:
    return next((r for r in rows if all(r.get(k) == v for k, v in match.items())), None)


def main() -> int:
    runs = {reader: {d: RESULTS / "willdaly" / rid for d, rid in ids.items()} for reader, ids in WILL.items()}
    runs.update(molsight_runs())
    readers = [r for r in ("MolScribe", "MolGlyph", "MolSight-extra", "MolSight-stereo") if r in runs]
    scores = {r: {d: read_scores(p) for d, p in runs[r].items()} for r in readers}

    def value(reader: str, dataset: str, metric: str, **match) -> str:
        row = pick(scores[reader].get(dataset, []), **match)
        return row.get(metric, "") if row else ""

    def n_label(dataset: str, **match) -> str:
        for r in readers:
            row = pick(scores[r].get(dataset, []), **match)
            if row and row.get("n_gt"):
                return f"{int(row['n_gt']):,}"
        return "?"

    recognition = []
    for structure, label in (("all", "all"), ("full", "full structures"), ("chiral", "chiral"),
                             ("markush", "Markush")):
        setting = f"BioVista test split, {label} ({n_label('biovista', subset='test', structure=structure)})"
        metrics = ["accuracy", "accuracy_stereo_blind", "mean_tanimoto", "accuracy_biovista"] if structure == "all" \
            else ["accuracy", "accuracy_stereo_blind"]
        for m in metrics:
            recognition.append((setting, m, [value(r, "biovista", m, subset="test", structure=structure)
                                             for r in readers]))
    test_all = {"subset": "test", "structure": "all"}
    no_output = []
    for r in readers:
        row = pick(scores[r].get("biovista", []), **test_all)
        no_output.append(str(int(row["n_gt"]) - int(row["n_output"]) + int(row["n_invalid"])) if row else "")
    recognition.append((f"BioVista test split, all ({n_label('biovista', **test_all)})",
                        "crops with no valid SMILES", no_output))
    for m in ("accuracy", "accuracy_stereo_blind", "mean_tanimoto"):
        recognition.append((f"Patent300 ground-truth crops ({n_label('patent300')})", m,
                            [value(r, "patent300", m) for r in readers]))

    end_to_end = []
    for agg in ("macro", "pooled"):
        metrics = ["precision", "recall", "f1", "recall_local_names"] if agg == "macro" else ["recall", "tp", "n_output"]
        for m in metrics:
            end_to_end.append((f"Internal papers ({agg}), MolDetV2 boxes, no margin", m,
                               [value(r, "internal", m, paper_id=agg) for r in readers]))

    lines = [
        "# Track 2: MolSight vs. MolScribe and MolGlyph",
        "",
        "Generated by `benchmarks/liba-jin/compare.py` from each run's `scores.csv`. Rates are fractions "
        "(0.7803 = 78.03%). Exact match of canonical SMILES unless the metric says otherwise; "
        "`accuracy_biovista` uses BioVista's own match rule (`benchmarks/score_biovista.py`). "
        "MolScribe and MolGlyph are Will's runs from #71; every reader saw the same crops.",
        "",
    ]
    csv_rows = []
    for title, table in (("Recognition on given crops", recognition),
                         ("Detection + recognition on the six internal papers", end_to_end)):
        lines += [f"## {title}", "", "| Setting | Metric | " + " | ".join(readers) + " |",
                  "|---|---|" + "---|" * len(readers)]
        for setting, metric, values in table:
            lines.append(f"| {setting} | {metric} | " + " | ".join(v or "-" for v in values) + " |")
            csv_rows.append({"section": title, "setting": setting, "metric": metric, **dict(zip(readers, values))})
        lines.append("")
    lines.append("Runs used: " + ", ".join(sorted(p.name for r in readers for p in runs[r].values())) + ".")
    (OUT / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(OUT / "comparison.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "setting", "metric", *readers])
        writer.writeheader()
        writer.writerows(csv_rows)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
