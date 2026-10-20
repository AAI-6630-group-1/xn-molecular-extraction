"""Tests for benchmarks/score_biovista.py (BioVista OCSR crops). Run with `pytest benchmarks/tests`."""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score  # noqa: E402
import score_biovista  # noqa: E402

# (crop stem, ground-truth SMILES). Paper 1_aaaa is in the test split, 2_bbbb in validation.
CROPS = [
    ("1_aaaa_image_molminer_bbox_1-0", "CCO"),
    ("1_aaaa_image_molminer_bbox_1-1", "C[C@H](N)C(=O)O"),
    ("1_aaaa_image_molminer_bbox_2-2", "[1*]c1ccc([2*])cc1"),
    ("2_bbbb_image_molminer_bbox_1-0", "*C(=O)O"),
]


@pytest.fixture
def root(tmp_path):
    """A miniature BioVista OCSR set. The label rows are deliberately out of crop-file order."""
    (tmp_path / "ocsr" / "data").mkdir(parents=True)
    (tmp_path / "ocsr" / "labels").mkdir()
    for stem, _ in CROPS:
        (tmp_path / "ocsr" / "data" / f"{stem}.png").write_bytes(b"")
    with open(tmp_path / "ocsr" / "labels" / "gd_SMIELS.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["", "pdf_name", "index", "molminer_id", "smiles"])
        for n, (stem, smiles) in enumerate(reversed(CROPS)):
            paper, index = score_biovista.crop_key(stem)
            writer.writerow([n, paper, index, f"P1-{index}", smiles])
    (tmp_path / "test_set_names.txt").write_text("1_aaaa\n")
    (tmp_path / "valid_set_names.txt").write_text("2_bbbb\n")
    return tmp_path


def make_run(results, rows, run_id="2026-10-06_molglyph_biovista", **meta):
    run_dir = results / "someone" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"task": "ocsr", "dataset": "biovista", **meta}))
    with open(run_dir / "predictions.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["paper_id", "smiles"])
        writer.writerows(rows)
    return run_dir


def test_load_truth_joins_on_key_not_row_order(root):
    truth = score_biovista.load_truth(root)
    assert truth["1_aaaa_image_molminer_bbox_1-1"].smiles == "C[C@H](N)C(=O)O"
    assert truth["2_bbbb_image_molminer_bbox_1-0"].split == "valid"
    assert truth["1_aaaa_image_molminer_bbox_2-2"].structures() == ["all", "markush"]
    assert truth["1_aaaa_image_molminer_bbox_1-1"].structures() == ["all", "full", "chiral"]


def test_biovista_match_rules():
    match = score_biovista.biovista_match
    assert match("OCC", "CCO")  # canonicalized
    assert match("CC(=O)[O-]", "CC(=O)O")  # charges are neutralized
    assert match("*c1ccccc1", "[1*]c1ccccc1")  # the first R1 label is dropped
    assert not match("*c1ccc(*)cc1", "[1*]c1ccc([2*])cc1")  # other labels must match
    assert not match("<invalid>", "CCO")
    assert not match(None, "CCO")


def test_score_run_counts_and_groups(root, tmp_path):
    run_dir = make_run(tmp_path / "results", [
        ("1_aaaa_image_molminer_bbox_1-0", "OCC"),  # correct
        ("1_aaaa_image_molminer_bbox_1-1", "CC(N)C(=O)O"),  # stereo lost: stereo-blind match only
        ("1_aaaa_image_molminer_bbox_2-2", "*c1ccc(*)cc1"),  # correct for score.py, not for BioVista's rule
        ("2_bbbb_image_molminer_bbox_1-0", "<invalid>"),
    ])
    rows = score.score_run(run_dir, ground_truth=root)
    by_group = {(r["subset"], r["structure"]): r for r in rows}

    everything = by_group[("all", "all")]
    assert (everything["n_gt"], everything["n_output"], everything["n_invalid"]) == (4, 4, 1)
    assert everything["exact"] == 2 and everything["accuracy"] == "0.5000"
    assert everything["accuracy_stereo_blind"] == "0.7500"
    assert everything["biovista_match"] == 1

    test_markush = by_group[("test", "markush")]
    assert (test_markush["n_gt"], test_markush["exact"], test_markush["biovista_match"]) == (1, 1, 0)
    assert by_group[("test", "chiral")]["exact"] == 0
    assert by_group[("test", "all")]["n_gt"] == 3

    with open(run_dir / "matches.csv", newline="") as f:
        matches = {r["crop"]: r for r in csv.DictReader(f)}
    assert matches["2_bbbb_image_molminer_bbox_1-0"]["output_valid"] == "False"


def test_unknown_crop_is_an_error(root, tmp_path):
    run_dir = make_run(tmp_path / "results", [("9_zzzz_image_molminer_bbox_1-0", "CCO")])
    with pytest.raises(score.ScoringError, match="not in the ground truth"):
        score.score_run(run_dir, ground_truth=root)


def test_crop_sample_scores_only_listed_crops(root, tmp_path):
    rows = [("1_aaaa_image_molminer_bbox_1-0", "OCC"), ("1_aaaa_image_molminer_bbox_1-1", "")]
    full = score.score_run(make_run(tmp_path / "full", rows), ground_truth=root)
    sample = score.score_run(make_run(tmp_path / "sample", rows, crop_sample=True), ground_truth=root)
    assert {(r["subset"], r["structure"]): r for r in full}[("all", "all")]["n_gt"] == 4
    everything = {(r["subset"], r["structure"]): r for r in sample}[("all", "all")]
    # the listed crop with an empty SMILES stays in the denominator as no output
    assert (everything["n_gt"], everything["n_output"], everything["exact"]) == (2, 1, 1)
