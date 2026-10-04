"""Tests for benchmarks/score.py. Run with `pytest benchmarks/tests`."""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score  # noqa: E402

# Paper 1 has three unique molecules; "A2" is a duplicate listing of "A", like the #63 duplicates.
GROUND_TRUTH = [
    ("1", "A", "CCO"),
    ("1", "B", "Oc1ccccc1"),
    ("1", "C", "C[C@H](N)C(=O)O"),
    ("1", "A2", "OCC"),
    ("2", "D", "CCN"),
]
TAGS = [
    ("1", "A", "public", ""),
    ("1", "A2", "local", ""),
    ("1", "B", "local", "single"),
    ("1", "C", "local", "reaction_scheme"),
]


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def gt(tmp_path):
    # Same column names as the real ground-truth file.
    return write_csv(tmp_path / "gt.csv", ["paperID", "name of molecule", "canonical_SMILES"], GROUND_TRUTH)


@pytest.fixture
def tags(tmp_path):
    return write_csv(tmp_path / "tags.csv", ["paper_id", "name", "name_type", "challenge"], TAGS)


def make_run(results, predictions, run_id="2026-10-05_molscribe_internal", handle="someone", meta=None):
    run_dir = results / handle / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps(meta or {"task": "e2e", "dataset": "internal"}))
    write_csv(run_dir / "predictions.csv", ["paper_id", "smiles", "page", "label", "source"], predictions)
    return run_dir


def by_paper(rows):
    return {r["paper_id"]: r for r in rows}


def test_equivalent_smiles_get_the_same_key():
    assert score.parse("OCC").key == score.parse("CCO").key
    assert score.parse("c1ccccc1O").key == score.parse("Oc1ccccc1").key


def test_r_group_placeholders_compare_equal():
    keys = {score.parse(s).key for s in ("[*:1]c1ccccc1", "[1*]c1ccccc1", "*c1ccccc1")}
    assert keys == {"*c1ccccc1"}


def test_stereo_blind_form_drops_stereo():
    assert score.parse("C[C@H](N)C(=O)O").stereo_blind == score.parse("CC(N)C(=O)O").key


def test_invalid_smiles():
    mol = score.parse("not a smiles")
    assert not mol.valid
    assert mol.key == "invalid:not a smiles"


def test_duplicate_ground_truth_rows_collapse(gt):
    truth = score.load_ground_truth(gt)
    assert len(truth["1"]) == 3
    assert truth["1"]["CCO"].names == ["A", "A2"]


def test_name_type_is_public_if_any_name_is(gt, tags):
    truth = score.load_ground_truth(gt, score.load_tags(tags))
    assert truth["1"]["CCO"].name_type == "public"
    assert truth["1"]["Oc1ccccc1"].name_type == "local"
    assert truth["2"]["CCN"].name_type == ""  # untagged


def test_score_run(tmp_path, gt, tags):
    run_dir = make_run(tmp_path / "results", [
        ("1", "OCC", "2", "12a", "drawing"),         # TP for A
        ("1", "CCO", "3", "", "name"),               # same molecule again: collapses into one output
        ("1", "CC(N)C(=O)O", "3", "", ""),           # C without its stereocenter: FP, but a stereo-blind match
        ("1", "not a smiles", "4", "", ""),          # invalid: counts as output and as wrong
        ("1", "c1ccccc1", "4", "", ""),              # benzene, near phenol (B): FP
        ("1", "", "5", "", ""),                      # empty SMILES rows are skipped
    ])
    rows = score.score_run(run_dir, gt, tags)
    p = by_paper(rows)

    assert p["1"]["n_gt"] == 3
    assert p["1"]["n_output_raw"] == 5
    assert p["1"]["n_output"] == 4
    assert p["1"]["n_invalid"] == 1
    assert p["1"]["tp"] == 1
    assert p["1"]["precision"] == "0.2500"
    assert p["1"]["recall"] == "0.3333"
    assert p["1"]["recall_stereo_blind"] == "0.6667"
    assert p["1"]["n_gt_local"] == 2
    assert p["1"]["recall_local_names"] == "0.0000"

    # Paper 2 got no predictions: precision is 0, not undefined.
    assert p["2"]["n_output"] == 0
    assert p["2"]["precision"] == p["2"]["recall"] == p["2"]["f1"] == "0.0000"
    assert p["2"]["mean_best_tanimoto"] == "0.0000"
    assert p["2"]["recall_local_names"] == ""  # no local molecules to score

    assert p["macro"]["precision"] == "0.1250"   # (0.25 + 0) / 2
    assert p["macro"]["recall"] == "0.1667"      # (1/3 + 0) / 2
    assert p["macro"]["recall_local_names"] == "0.0000"  # only paper 1 has local molecules
    assert p["pooled"]["precision"] == "0.2500"  # 1 / 4
    assert p["pooled"]["recall"] == "0.2500"     # 1 / 4
    assert p["pooled"]["n_gt"] == 4

    assert (run_dir / "scores.csv").exists()
    assert p["1"]["handle"] == "someone"
    assert p["1"]["tool"] == "molscribe"


def test_matches_csv(tmp_path, gt, tags):
    run_dir = make_run(tmp_path / "results", [
        ("1", "OCC", "2", "12a", "drawing"),
        ("1", "CCO", "3", "", "name"),
        ("1", "c1ccccc1", "4", "", ""),
    ])
    score.score_run(run_dir, gt, tags)
    matches = read_csv(run_dir / "matches.csv")
    gt_rows = {r["names"]: r for r in matches if r["side"] == "gt"}
    pred_rows = {r["smiles"]: r for r in matches if r["side"] == "pred"}

    assert gt_rows["A; A2"]["status"] == "TP"
    assert gt_rows["A; A2"]["best_tanimoto"] == "1.0000"
    assert gt_rows["B"]["status"] == "FN"
    assert gt_rows["B"]["nearest_smiles"] == "c1ccccc1"
    assert gt_rows["B"]["challenge"] == "single"

    assert pred_rows["CCO"]["status"] == "TP"
    assert pred_rows["CCO"]["n_rows"] == "2"
    assert pred_rows["CCO"]["sources"] == "drawing; name"
    assert pred_rows["CCO"]["pages"] == "2; 3"
    assert pred_rows["c1ccccc1"]["status"] == "FP"
    assert pred_rows["c1ccccc1"]["nearest_names"] == "B"


def test_unknown_paper_is_an_error(tmp_path, gt):
    run_dir = make_run(tmp_path / "results", [("3", "CCO", "", "", "")])
    with pytest.raises(score.ScoringError, match="not in the ground truth"):
        score.score_run(run_dir, gt)


def test_unknown_source_is_an_error(tmp_path, gt):
    run_dir = make_run(tmp_path / "results", [("1", "CCO", "", "", "memory")])
    with pytest.raises(score.ScoringError, match="source must be one of"):
        score.score_run(run_dir, gt)


def test_other_tasks_are_not_supported_yet(tmp_path, gt):
    run_dir = make_run(tmp_path / "results", [], meta={"task": "ocsr", "dataset": "internal"})
    with pytest.raises(score.ScoringError, match="only has e2e scoring"):
        score.score_run(run_dir, gt)


def test_score_all_writes_summary_and_reports_errors(tmp_path, gt):
    results = tmp_path / "results"
    make_run(results, [("1", "CCO", "", "", "")], handle="a")
    make_run(results, [("1", "CCN", "", "", "")], handle="b")
    make_run(results, [], handle="c", meta={"dataset": "internal"})  # no task
    summary, errors = score.score_all(results, gt, tmp_path / "no-tags.csv")

    assert {r["handle"] for r in summary} == {"a", "b"}
    assert len(read_csv(results / "summary.csv")) == len(summary) == 2 * 4  # 2 papers + macro + pooled
    assert len(errors) == 1 and "needs a 'task' field" in errors[0]


@pytest.mark.skipif(not score.GROUND_TRUTH["internal"].exists(), reason="internal dataset not in data/internal/")
def test_real_ground_truth_scores_perfectly_against_itself(tmp_path):
    """The real file's quirks (duplicates, R-group placeholders, a salt) survive a round trip."""
    with open(score.GROUND_TRUTH["internal"], newline="", encoding="utf-8-sig") as f:
        rows = [(r["paperID"], r["canonical_SMILES"], "", "", "") for r in csv.DictReader(f)]
    run_dir = make_run(tmp_path / "results", rows)
    p = by_paper(score.score_run(run_dir))

    assert p["pooled"]["n_gt"] == 220
    assert p["pooled"]["n_gt_local"] == 190
    for paper in ("1", "2", "4", "6", "16", "19", "macro", "pooled"):
        assert p[paper]["precision"] == p[paper]["recall"] == "1.0000", paper
