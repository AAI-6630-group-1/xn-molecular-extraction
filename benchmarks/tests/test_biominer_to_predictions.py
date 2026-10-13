"""Tests for benchmarks/willdaly/biominer_to_predictions.py. Run with `pytest benchmarks/tests`."""

import csv
import json
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "willdaly"))
import biominer_to_predictions as convert  # noqa: E402

FULL_SUFFIX = "moldetv2_bbox_molglyph_ocsr_updated"
LOG = """job:     11040999 xn-biominer on d4052, partition gpu
commit:  abc1234
gpu:     NVIDIA H200, 570.86.15, 143771 MiB
pipeline: exit 0 after 812 s
llm calls that failed: 0
"""


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ligand", "smiles"])
        writer.writerows(rows)


def fake_run(tmp_path, rendered_pages=2):
    """A BioMiner output folder for one two-page paper, "7", as run.sbatch packs it."""
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    doc = fitz.open()
    doc.new_page(width=600, height=800)
    doc.new_page(width=600, height=800)
    doc.save(pdf_dir / "7.pdf")

    out = tmp_path / "out" / "2026-10-13_biominer_internal"
    (out / "page_images" / "7").mkdir(parents=True)
    for i in range(rendered_pages):
        (out / "page_images" / "7" / f"7_image_{i}.png").write_bytes(b"")
    (out / "biominer_upgrade.txt").write_text("7")
    boxes = [[{"index": 0, "page": 1, "bbox": [0.1, 0.25, 0.5, 0.25], "smiles": "CCO"},
              {"index": 1, "page": 1, "bbox": [0.0, 0.0, 0.1, 0.1], "smiles": ""}]]
    (out / "biominer_upgrade_ocsr_output.json").write_text(json.dumps(boxes))

    paper = out / "extraction_local-biominer-instruct" / "7"
    paper.mkdir(parents=True)
    write_csv(paper / f"7_structure_full_output_{FULL_SUFFIX}.csv", [("12a", "CCO")])
    write_csv(paper / f"7_structure_part_output_{FULL_SUFFIX}.csv", [("13b", "CCN"), ("13c", "")])
    write_csv(paper / f"7_structure_merged_output_{FULL_SUFFIX}_{FULL_SUFFIX}.csv", [("12a", "CCO"), ("13b", "CCN")])
    (tmp_path / "slurm.out").write_text(LOG)
    return out, pdf_dir


def run(monkeypatch, tmp_path, out, pdf_dir):
    results = tmp_path / "results"
    monkeypatch.setattr(sys, "argv", ["biominer_to_predictions.py", str(out), "--pdf-dir", str(pdf_dir),
                                      "--results", str(results), "--slurm-log", str(tmp_path / "slurm.out")])
    assert convert.main() == 0
    return results


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_final_run_tags_each_row_with_its_stage(monkeypatch, tmp_path):
    out, pdf_dir = fake_run(tmp_path)
    results = run(monkeypatch, tmp_path, out, pdf_dir)
    rows = read(results / "2026-10-13_biominer_internal" / "predictions.csv")
    assert [(r["label"], r["smiles"], r["stage"]) for r in rows] == [("12a", "CCO", "full"), ("13b", "CCN", "markush")]
    meta = json.loads((results / "2026-10-13_biominer_internal" / "run.json").read_text())
    assert (meta["task"], meta["dataset"], meta["tool"]) == ("e2e", "internal", "biominer")
    assert meta["counts"]["7"] == {"pages": 2, "rendered_pages": 2, "boxes": 2, "full_rows": 1, "markush_rows": 1}
    assert meta["hardware"] == "Explorer d4052, NVIDIA H200, 570.86.15, 143771 MiB"
    assert (meta["slurm_job"], meta["git_commit"], meta["runtime_s"], meta["llm_failures"]) == ("11040999", "abc1234", {"all_papers": 812}, 0)


def test_stage1_run_converts_boxes_to_pdf_points(monkeypatch, tmp_path):
    out, pdf_dir = fake_run(tmp_path)
    results = run(monkeypatch, tmp_path, out, pdf_dir)
    rows = read(results / "2026-10-13_biominer-stage1_internal" / "predictions.csv")
    assert len(rows) == 1  # the box without a SMILES is left out
    row = rows[0]
    assert (row["paper_id"], row["smiles"], row["page"], row["box_id"]) == ("7", "CCO", "2", "7-p2-0")
    assert [float(row[k]) for k in ("x0", "y0", "x1", "y1")] == [60.0, 200.0, 360.0, 400.0]


def test_missing_page_images_fail_loudly(monkeypatch, tmp_path):
    out, pdf_dir = fake_run(tmp_path, rendered_pages=0)
    with pytest.raises(SystemExit, match="0 page images for 2 PDF pages"):
        run(monkeypatch, tmp_path, out, pdf_dir)
