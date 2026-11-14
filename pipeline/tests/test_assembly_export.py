"""Tests for R-group assembly and export (Will's 2.3 module).

The fixture in fixtures/assembly_run/ is a hand-made two-page paper; its
expected/ folder holds the output these tests require. The join tests use real
MolGlyph readings from the six internal papers.

AI disclosure: Claude Code wrote these tests at Will's request, for his review.
"""
import csv
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "benchmarks"))

from pipeline import smoke
from pipeline.assembly import Abstain, assemble_row, assemble_run, join
from pipeline.export import export_run
from pipeline.phase1_run import convert
from pipeline.stage_io import (PREDICTION_COLUMNS, attachment_points, parse_smiles, read_csv,
                               read_jsonl, select_reading)
from pipeline.substituents import FRAGMENTS, column_position, text_fragment

FIXTURE = Path(__file__).parent / "fixtures" / "assembly_run"


@pytest.fixture
def run(tmp_path):
    """A fresh copy of the fixture run, with assembly and export already applied."""
    run_dir = tmp_path / "run"
    shutil.copytree(FIXTURE / "input", run_dir)
    assemble_run(run_dir)
    export_run(run_dir)
    return run_dir


# --- the whole module on the fixture ---------------------------------------

def test_fixture_outputs_match_expected(run):
    expected = FIXTURE / "expected"
    assert read_jsonl(run / "papers/fx/assemblies.jsonl") == read_jsonl(expected / "assemblies.jsonl")
    assert read_csv(run / "predictions.csv") == read_csv(expected / "predictions.csv")
    assert read_jsonl(run / "provenance.jsonl") == read_jsonl(expected / "provenance.jsonl")
    assert read_jsonl(run / "export_rejections.jsonl") == read_jsonl(expected / "export_rejections.jsonl")


def test_one_assembly_record_per_table_row(run):
    records = {r["label"]: r for r in read_jsonl(run / "papers/fx/assemblies.jsonl")}
    assert len(records) == 8
    assert records["13a"]["smiles"] == "COc1ccc(C(N)=O)cc1"          # text cell
    assert records["13b"]["smiles"] == "CCOc1ccc(C(N)=O)cc1"         # drawn cell
    assert records["13b"]["source_box_ids"] == ["fx-p1-1", "fx-p1-4"]
    assert records["13d"]["smiles"] == "NC(=O)c1ccccc1"              # "-H" removes the point
    assert records["20b"]["smiles"] == "Cc1ccc(Cl)cc1C(=O)O"         # R1 and R2 by number
    for label, reason in (("13c", "abbreviation table"), ("30a", "cannot tell which column"),
                          ("40a", "link abstained")):
        assert records[label]["status"] == "abstain" and records[label]["smiles"] is None
        assert reason in records[label]["reason"]


def test_export_keeps_only_complete_molecules(run):
    rows = read_csv(run / "predictions.csv")
    assert list(rows[0]) == PREDICTION_COLUMNS
    assert all("*" not in row["smiles"] for row in rows)
    assert {row["source"] for row in rows} == {"drawing", "unknown"}
    assert all(row["method"] == "r_group_assembly" for row in rows if row["source"] == "unknown")
    exported_boxes = {row["box_id"] for row in rows if row["method"] == "reading"}
    # complete drawing and consensus reading in; plot, uncertain gate, abstention, bad SMILES out
    assert exported_boxes == {"fx-p1-0", "fx-p2-2"}
    assert len({row["prediction_id"] for row in rows}) == len(rows)


def test_every_prediction_has_provenance_and_counts_add_up(run):
    predictions = read_csv(run / "predictions.csv")
    provenance = {row["prediction_id"]: row for row in read_jsonl(run / "provenance.jsonl")}
    assert set(provenance) == {row["prediction_id"] for row in predictions}
    stages = json.loads((run / "run.json").read_text())["stages"]
    assert stages["assemble"] == {**stages["assemble"], "status": "complete", "ok": 5, "abstain": 3, "error": 0}
    counts = stages["export"]["counts"]
    assert counts["drawing_exported"] + counts["assembly_exported"] == len(predictions) == 7
    # 10 regions: each one is exported, rejected, abstained or gated out
    regions = (counts["drawing_exported"] + counts["unresolved_wildcard"] + counts["parse_failure"]
               + counts["reading_abstained"] + counts["gate_non_molecule"] + counts["gate_uncertain"])
    assert regions == 10


def test_uncertain_gate_is_an_explicit_choice(tmp_path):
    run_dir = tmp_path / "run"
    shutil.copytree(FIXTURE / "input", run_dir)
    assemble_run(run_dir)
    export_run(run_dir, gates=("molecule", "uncertain"))
    assert "fx-p1-3" in {row["box_id"] for row in read_csv(run_dir / "predictions.csv")}


def test_missing_stage_file_is_an_error(tmp_path):
    run_dir = tmp_path / "run"
    shutil.copytree(FIXTURE / "input", run_dir)
    (run_dir / "papers/fx/links.jsonl").unlink()
    with pytest.raises(FileNotFoundError):
        assemble_run(run_dir)


def test_malformed_row_is_recorded_as_error():
    table = {"paper_id": "fx", "table_id": "t", "columns": [{"column_id": "c0", "heading": "R"}]}
    row = {"row_id": "t-r0", "label": "1", "cells": [{"text": "Me"}]}  # cell without column_id
    record = assemble_row(table, row, [], {})
    assert record["status"] == "error" and "KeyError" in record["reason"]


# --- joining pieces ---------------------------------------------------------

def test_join_real_readings_from_paper_4_and_19():
    # Both pairs are MolGlyph readings from the Phase 1 run (assembly_example.txt).
    assert join("*COc1cccc2c1C(=O)N(C1CCC(=O)NC1=O)C2=O",
                [(None, "*COCCOCCOCCNC(=O)OC(C)(C)C")]) == (
        "CC(C)(C)OC(=O)NCCOCCOCCOCCOc1cccc2c1C(=O)N(C1CCC(=O)NC1=O)C2=O")   # paper 4, compound 6
    assert join("CCCS(=O)(=O)Nc1ccc(F)c(C(=O)c2ccc3[nH]c4ncc(*)cc4c3c2)c1F",
                [(None, "*c1ccnnc1")]) == (
        "CCCS(=O)(=O)Nc1ccc(F)c(C(=O)c2ccc3[nH]c4ncc(-c5ccnnc5)cc4c3c2)c1F")  # paper 19, compound 19


def test_join_keeps_stereochemistry():
    assert join("C[C@H](*)N", [(None, "*O")]) == "C[C@@H](N)O"
    assert parse_smiles("C[C@@H](N)O") is not None


def test_join_by_number_ignores_column_order():
    scaffold = "[1*]c1ccc([2*])c(C(=O)O)c1"
    assert join(scaffold, [(2, "*C"), (1, "*Cl")]) == join(scaffold, [(1, "*Cl"), (2, "*C")])


@pytest.mark.parametrize("scaffold, pieces, reason", [
    # paper 2's scaffold: five unnumbered points, so the columns cannot be placed
    ("Nc1c(*)c(*)c(*)c(*)c1*", [(n, "*F") for n in range(1, 6)], "cannot tell which column"),
    ("[1*]c1ccc([2*])cc1", [(1, "*F"), (3, "*C")], "no R3"),
    ("[1*]c1ccc([2*])cc1", [(1, "*F")], "have no table column"),
    ("*c1ccccc1", [(None, "*CC*")], "not a one-point fragment"),
    ("c1ccccc1", [(None, "*F")], "no attachment point"),
    ("not smiles", [(None, "*F")], "not valid SMILES"),
])
def test_join_abstains_instead_of_guessing(scaffold, pieces, reason):
    with pytest.raises(Abstain, match=reason):
        join(scaffold, pieces)


# --- table text -------------------------------------------------------------

def test_every_abbreviation_is_a_one_point_fragment():
    for name, smiles in FRAGMENTS.items():
        mol = parse_smiles(smiles)
        assert mol is not None and len(attachment_points(mol)) == 1, name


@pytest.mark.parametrize("text, fragment", [
    ("OMe", "*OC"), ("-F", "*F"), ("–OCH₃", "*OC"), (" CF3 ", "*C(F)(F)F"), ("H", "*[H]"),
    ("4-F-Ph", None), ("morpholine", None), ("", None), ("me", None),
    # paper 19, Table 6 spellings
    ("-CH2-CH3", "*CC"), ("nC3H7", "*CCC"), ("nC6H13", "*CCCCCC"), ("cyclo-prop", "*C1CC1"),
    ("-CH2-iprop", "*CC(C)C"), ("-(CH2)2-iprop", "*CCC(C)C"), ("c-hexyl", "*C1CCCCC1"),
    ("-phenyl", "*c1ccccc1"), ("-benzyl", "*Cc1ccccc1"), ("-(CH2)2-CF3", "*CCC(F)(F)F"),
    ("-CH2-C(O)-CH3", "*CC(C)=O"), ("-CH2-C(OH)-CH3", "*CC(C)O"),
    ("-CH2-(o)F-phenyl", "*Cc1ccccc1F"), ("-CH2-(p)F-phenyl", "*Cc1ccc(F)cc1"),
    # ambiguous or malformed: abstain
    ("-ethylphenyl", None), ("nC3H8", None), ("cC6H11", None), ("nC0H1", None),
])
def test_text_fragment(text, fragment):
    assert text_fragment(text) == fragment


@pytest.mark.parametrize("heading, expected", [
    ("R1", (True, 1)), ("R₂", (True, 2)), ("R^3", (True, 3)), ("R", (True, None)),
    ("Ra", (True, None)), ("R'", (True, None)), ("X", (False, None)), ("Ar", (False, None)),
    ("Compd", (False, None)), ("IC50 (nM)", (False, None)), ("Yield", (False, None)),
])
def test_column_position(heading, expected):
    assert column_position(heading) == expected


def test_select_reading_prefers_consensus_and_does_not_fall_through():
    rows = [{"reader": "molscribe", "status": "ok"}, {"reader": "molglyph", "status": "abstain"}]
    assert select_reading(rows)["reader"] == "molglyph"   # primary reader's abstention stands
    assert select_reading(rows + [{"reader": "consensus", "status": "ok"}])["reader"] == "consensus"
    assert select_reading([]) is None


# --- fit with the rest of the repo -----------------------------------------

def test_columns_match_the_smoke_runner():
    assert PREDICTION_COLUMNS == smoke.PREDICTION_COLUMNS


def test_phase1_run_exports_and_scores_with_the_existing_scorer(tmp_path):
    """Phase 1 predictions -> stage files -> export -> benchmarks/score.py, with a two-row answer key."""
    from score import score_run
    source = tmp_path / "2026-01-01_tool_internal"
    source.mkdir()
    (source / "run.json").write_text(json.dumps({
        "handle": "test", "tool": "tool", "task": "e2e", "dataset": "internal",
        "settings": {"reader": "molglyph"}, "versions": {}}))
    with (source / "predictions.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow("paper_id smiles page x0 y0 x1 y1 label source confidence det_confidence box_id".split())
        writer.writerow(["1", "OCC", 1, 0, 0, 10, 10, "", "drawing", 0.9, 0.8, "1-p1-0"])   # correct
        writer.writerow(["1", "*c1ccccc1", 1, 20, 0, 30, 10, "", "drawing", 0.9, 0.8, "1-p1-1"])  # fragment
        writer.writerow(["1", "", 2, 0, 0, 10, 10, "", "drawing", "", 0.6, "1-p2-0"])       # abstention
    truth = tmp_path / "gt.csv"
    truth.write_text("paperID,name of molecule,canonical_SMILES\n1,ethanol,CCO\n1,toluene,Cc1ccccc1\n")

    run_dir = tmp_path / "pipeline_run"
    convert(source, run_dir)
    assemble_run(run_dir)
    info = export_run(run_dir)
    assert info["counts"] == {"drawing_exported": 1, "reading_abstained": 1, "unresolved_wildcard": 1}
    paper = next(row for row in score_run(run_dir, ground_truth=truth) if row["paper_id"] == "1")
    assert (int(paper["n_output"]), int(paper["tp"]), int(paper["n_gt"])) == (1, 1, 2)
    with pytest.raises(FileExistsError):
        convert(source, run_dir)


def test_export_marks_a_frontend_run_as_e2e(run):
    """A run the front end labelled `frontend` becomes scoreable once export has run."""
    meta_path = run / "run.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("producer_task", None)
    meta_path.write_text(json.dumps({**meta, "task": "frontend"}))
    export_run(run)
    meta = json.loads(meta_path.read_text())
    assert (meta["task"], meta["producer_task"]) == ("e2e", "frontend")
