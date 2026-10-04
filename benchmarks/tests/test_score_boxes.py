"""Tests for benchmarks/score_boxes.py (Patent300-style box datasets). Run with `pytest benchmarks/tests`."""

import csv
import json
import sys
from pathlib import Path

import pytest
from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score  # noqa: E402
import score_boxes  # noqa: E402

# Two pages. Page pA has two molecules and a text box; page pB has one molecule.
PAGES = {
    "pA": [(0, [0, 0, 100, 100], 1, "CCO"), (1, [0, 110, 30, 20], 2, None), (2, [200, 0, 100, 100], 1, "Oc1ccccc1")],
    "pB": [(0, [0, 0, 50, 50], 1, "C[C@H](N)C(=O)O")],
}


@pytest.fixture
def root(tmp_path):
    """A miniature Patent300: json/patent_300_huggingface.json plus one molfile per structure box."""
    (tmp_path / "json").mkdir()
    (tmp_path / "mol").mkdir()
    images = []
    for page, boxes in PAGES.items():
        images.append({"file_name": f"{page}.png", "dla_bboxes": [
            {"id": i, "bbox": bbox, "category_id": cat} for i, bbox, cat, _ in boxes]})
        for i, _, cat, smiles in boxes:
            if cat == 1:
                (tmp_path / "mol" / f"{page}_bbox_{i}.mol").write_text(Chem.MolToMolBlock(Chem.MolFromSmiles(smiles)))
    (tmp_path / "json" / "patent_300_huggingface.json").write_text(json.dumps({"images": images}))
    return tmp_path


def make_run(results, task, header, rows, run_id="2026-10-04_moldetv2_patent300", meta=None):
    run_dir = results / "someone" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"task": task, "dataset": "patent300", **(meta or {})}))
    with open(run_dir / "predictions.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return run_dir


def test_load_truth_keeps_structures_only(root):
    truth = score_boxes.load_truth(root)
    assert [b.id for b in truth["pA"]] == ["pA_bbox_0", "pA_bbox_2"]
    assert (truth["pA"][1].x1, truth["pA"][1].y1) == (300, 100)  # [x, y, w, h] -> corners
    assert truth["pB"][0].molecule.key == score.parse("C[C@H](N)C(=O)O").key


def test_iou():
    a = score_boxes.Box("p", 0, 0, 100, 100)
    ious = score_boxes.iou_matrix([a], [a, score_boxes.Box("p", 50, 0, 150, 100), score_boxes.Box("p", 200, 0, 300, 100)])
    assert ious[0] == pytest.approx([1.0, 1 / 3, 0.0])


def test_detect_perfect(root, tmp_path):
    rows = [(p, x, y, x + w, y + h, 0.9) for p, boxes in PAGES.items() for _, (x, y, w, h), cat, _ in boxes if cat == 1]
    run_dir = make_run(tmp_path / "results", "detect", ["paper_id", "x0", "y0", "x1", "y1", "confidence"], rows)
    (row,) = score.score_run(run_dir, root)
    assert row["ap"] == row["ar"] == row["f1_coco"] == row["precision50"] == row["recall50"] == "1.0000"


def test_detect_matches_hand_computed_coco(root, tmp_path):
    run_dir = make_run(tmp_path / "results", "detect", ["paper_id", "x0", "y0", "x1", "y1", "confidence"], [
        ("pA", 500, 500, 600, 600, 0.95),  # false positive, highest score
        ("pA", 0, 0, 100, 100, 0.9),       # exact match for pA_bbox_0
        ("pB", 0, 0, 40, 40, 0.5),         # IoU 0.64 with pB_bbox_0: a match at IoU 0.50-0.60 only
    ], meta={"score_threshold": 0.6})
    (row,) = score.score_run(run_dir, root)

    # At IoU 0.50, 0.55, 0.60 the ranked hits are FP, TP, TP: precision 2/3 up to recall 2/3,
    # which covers 67 of COCO's 101 recall points. At the 7 stricter thresholds, FP, TP, FP:
    # precision 1/2 up to recall 1/3, 34 points.
    ap_loose, ap_strict = 67 * (2 / 3) / 101, 34 * 0.5 / 101
    assert float(row["ap50"]) == pytest.approx(ap_loose, abs=1e-4)
    assert float(row["ap"]) == pytest.approx((3 * ap_loose + 7 * ap_strict) / 10, abs=1e-4)
    assert float(row["ar"]) == pytest.approx((3 * 2 / 3 + 7 * 1 / 3) / 10, abs=1e-4)

    # The operating point keeps the two boxes scoring >= 0.6: one hit.
    assert (row["n_pred_used"], row["tp50"]) == (2, 1)
    assert row["precision50"] == "0.5000" and row["recall50"] == "0.3333"
    # Keeping all three boxes gives the best F1 (2/3).
    assert row["best_f1_50"] == "0.6667" and row["best_f1_threshold"] == "0.5000"

    matches = {(r["side"], r["id"]): r["status"] for r in csv.DictReader(open(run_dir / "matches.csv"))}
    assert matches[("gt", "pA_bbox_2")] == "FN"
    assert matches[("gt", "pB_bbox_0")] == "FN"  # its only match scores below the operating point
    assert matches[("pred", "4")] == "below_threshold"


def test_ocsr(root, tmp_path):
    run_dir = make_run(tmp_path / "results", "ocsr", ["paper_id", "smiles"], [
        ("pA_bbox_0", "OCC"),        # correct
        ("pA_bbox_2", "c1ccccc1"),   # wrong: benzene for phenol
    ], run_id="2026-10-04_molscribe_patent300")              # pB_bbox_0 has no output: wrong, similarity 0
    (row,) = score.score_run(run_dir, root)
    assert (row["n_gt"], row["n_output"], row["exact"]) == (3, 2, 1)
    assert row["accuracy"] == row["accuracy_stereo_blind"] == "0.3333"
    benzene_phenol = score_boxes._tanimoto(score.parse("Oc1ccccc1"), score.parse("c1ccccc1"))
    assert float(row["mean_tanimoto"]) == pytest.approx((1 + benzene_phenol) / 3, abs=1e-4)


def test_ocsr_rejects_two_answers_for_one_crop(root, tmp_path):
    run_dir = make_run(tmp_path / "results", "ocsr", ["paper_id", "smiles"], [("pA_bbox_0", "CCO"), ("pA_bbox_0", "CCN")])
    with pytest.raises(score.ScoringError, match="more than one SMILES"):
        score.score_run(run_dir, root)


def test_e2e_follows_molmole_equation_1(root, tmp_path):
    run_dir = make_run(tmp_path / "results", "e2e", ["paper_id", "smiles", "x0", "y0", "x1", "y1"], [
        ("pA", "CCO", 0, 0, 100, 100),            # right box, right molecule: TP
        ("pA", "c1ccccc1", 200, 0, 300, 100),     # right box, wrong molecule
        ("pA", "CCCC", 500, 500, 600, 600),       # no molecule there
        ("pB", "CC(N)C(=O)O", 0, 0, 40, 40),      # right box (IoU 0.64), stereocenter lost
    ], run_id="2026-10-04_moldetv2-molscribe_patent300")
    (row,) = score.score_run(run_dir, root)
    assert (row["n_pred"], row["detected50"], row["tp"]) == (4, 3, 1)
    assert row["precision"] == "0.2500" and row["recall"] == "0.3333"


def test_unknown_page_is_an_error(root, tmp_path):
    run_dir = make_run(tmp_path / "results", "detect", ["paper_id", "x0", "y0", "x1", "y1"], [("pZ", 0, 0, 1, 1)])
    with pytest.raises(score.ScoringError, match="not in the ground truth"):
        score.score_run(run_dir, root)


def test_score_all_writes_one_summary_per_task(root, tmp_path, monkeypatch):
    results = tmp_path / "results"
    make_run(results, "detect", ["paper_id", "x0", "y0", "x1", "y1"], [("pA", 0, 0, 100, 100)])
    monkeypatch.setitem(score.BOX_DATASETS, "patent300", root)
    summary, errors = score.score_all(results)
    assert not errors and len(summary) == 1
    assert (results / "summary_detect_patent300.csv").exists()
    assert (results / "summary.csv").read_text().startswith("run_id,")  # still written, empty, for 1.5
