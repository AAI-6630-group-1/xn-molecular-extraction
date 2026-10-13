"""Tests for benchmarks/aggregate.py. Run with `pytest benchmarks/tests`."""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aggregate  # noqa: E402

FIELDS = ["run_id", "handle", "tool", "dataset", "paper_id", "n_gt", "n_output_raw", "n_output", "n_invalid", "tp",
          "precision", "recall", "f1", "rdkit_version"]
N_GT = {"1": 17, "2": 34, "4": 60, "6": 1, "16": 4, "19": 104}


def internal_rows(run_id, handle, tool, tp_per_paper, rdkit="2026.03.2"):
    rows = []
    for paper, n in N_GT.items():
        tp = tp_per_paper.get(paper, 0)
        rows.append([run_id, handle, tool, "internal", paper, n, 10, 10, 0, tp, tp / 10, tp / n, 0.5, rdkit])
    total = sum(tp_per_paper.values())
    rows.append([run_id, handle, tool, "internal", "macro", 220, 60, 60, 0, total, 0.5, 0.3, 0.4, rdkit])
    rows.append([run_id, handle, tool, "internal", "pooled", 220, 60, 60, 0, total, total / 60, total / 220, 0.4, rdkit])
    return rows


def write_run_json(results, handle, run_id, **meta):
    folder = results / handle / run_id
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps({"task": "e2e", "dataset": "internal", **meta}))


def make_results(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    rows = (internal_rows("2026-10-01_toola_internal", "alice", "toola", {"1": 5})
            + internal_rows("2026-10-09_toola_internal", "alice", "toola", {"1": 9, "2": 3})
            + internal_rows("2026-10-09_toolb_internal", "bob", "toolb", {"16": 2}, rdkit="2025.03.1"))
    with open(results / "summary.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    write_run_json(results, "alice", "2026-10-01_toola_internal", git_commit="aaa1111")
    write_run_json(results, "alice", "2026-10-09_toola_internal", git_commit="bbb2222-dirty",
                   counts={p: {} for p in N_GT})
    write_run_json(results, "bob", "2026-10-09_toolb_internal", git_commit="ccc3333", counts={"16": {}})
    return results


def test_latest_run_per_tool_and_flags(tmp_path, monkeypatch):
    results = make_results(tmp_path)
    monkeypatch.setattr(aggregate, "SYSTEMS", {"Tool A": {("e2e", "internal"): "toola"}, "Tool C": {("e2e", "internal"): "toolc"}})
    assert aggregate.main(results) == 0
    md = (results / "comparison.md").read_text()

    internal = [l for l in md.splitlines() if l.startswith("| [alice") or l.startswith("| [bob")]
    assert len(internal) == 2  # alice's older toola run is dropped
    assert internal[0].startswith("| [alice / toola](alice/2026-10-09_toola_internal) | 9/17 | 3/34 |")  # sorted by number found
    bob = internal[1]
    assert "covers papers 16 only" in bob and "scored with RDKit 2025.03.1" in bob

    runs = [l for l in md.splitlines() if l.startswith("| [2026-10-09_toola")]
    assert runs and runs[0].rstrip().endswith("run from uncommitted code |")

    systems = list(csv.DictReader(open(results / "comparison.csv")))
    assert [s["system"] for s in systems] == ["Tool A", "Tool C"]
    assert float(systems[0]["Internal papers (pooled recall)"]) == 12 / 220
    assert systems[1]["Internal papers (pooled recall)"] == ""  # Tool C has no run
    assert "| Tool C | not run |" in md


def test_no_runs_is_an_error(tmp_path):
    (tmp_path / "results").mkdir()
    assert aggregate.main(tmp_path / "results") == 1
