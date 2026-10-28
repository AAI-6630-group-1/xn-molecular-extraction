"""Guard the diagnostic's coordinate and honest-status boundaries."""
import csv
import json
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.smoke import run_smoke


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "input.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.insert_text((80, 100), "Molecule label 12a")
        page.set_cropbox(pymupdf.Rect(20, 30, 280, 370))
        page.set_rotation(90)
        doc.save(path)
    return path


def test_rotated_crop_coordinates_and_empty_predictions(pdf, tmp_path):
    out = tmp_path / "run"
    meta = run_smoke(pdf, "6", out, dpi=144)
    page = json.loads((out / "papers/6/pages.jsonl").read_text())
    block = json.loads((out / "papers/6/text.jsonl").read_text())
    transform = pymupdf.Matrix(*page["pixel_to_pdf"])
    with pymupdf.open(pdf) as doc:
        point = pymupdf.Point(block["x0"], block["y0"])
        rendered = point * doc[0].rotation_matrix * pymupdf.Matrix(2, 2)
        restored = rendered * transform
    assert (restored.x, restored.y) == pytest.approx((point.x, point.y))
    assert page["width_px"] == 680 and page["height_px"] == 520
    assert (out / page["image_path"]).exists()
    assert meta["task"] == "smoke" and meta["dataset"] == "pipeline-smoke"
    assert meta["stages"]["detect_gate_tables"]["status"] == "stub"
    with (out / "predictions.csv").open() as stream:
        assert list(csv.DictReader(stream)) == []
    assert not (out / "scores.csv").exists()


def test_existing_run_is_not_overwritten(pdf, tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "run.json"
    sentinel.write_text("original")
    with pytest.raises(FileExistsError):
        run_smoke(pdf, "6", out)
    assert sentinel.read_text() == "original"


def test_bad_paper_id_does_not_escape_output(pdf, tmp_path):
    with pytest.raises(ValueError, match="simple identifier"):
        run_smoke(pdf, "../outside", tmp_path / "run")


def test_failure_is_recorded_as_error(pdf, tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("render failed")
    monkeypatch.setattr("pipeline.smoke.render_document", fail)
    out = tmp_path / "failed"
    with pytest.raises(RuntimeError):
        run_smoke(pdf, "6", out)
    meta = json.loads((out / "run.json").read_text())
    assert meta["status"] == "error" and "render failed" in meta["error"]


def test_benchmark_scorer_rejects_smoke(pdf, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))
    from score import ScoringError, score_run
    out = tmp_path / "run"
    run_smoke(pdf, "6", out)
    with pytest.raises(ScoringError, match="only has e2e scoring"):
        score_run(out)
