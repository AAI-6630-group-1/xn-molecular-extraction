"""Tests for the reading and consensus stage (Bijay's 2.3 module).

Fake readers stand in for MolGlyph and MolScribe, so the tests need no model
weights and run on a CPU in seconds. The fixture run is built in a temp folder:
one complete drawing, one R-group scaffold (with MolGlyph's `*` labels), one
region both readers fail on, one uncertain region, and one rejected non-molecule.

AI disclosure: Took Claude Code help.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import reading
from pipeline.reading import (READERS, build_consensus, canonical, consensus_row, error_row, main, read_paper,
                              read_run, reader_row)
from pipeline.smoke import READING_COLUMNS
from pipeline.stage_io import labelled_scaffold, read_csv, select_reading, write_csv

REGION_COLUMNS = "paper_id page box_id x0 y0 x1 y1 crop_path role gate confidence reason".split()
# MolGlyph raw output of paper 19's scaffold 19-p3-0: SMILES, <sep>, then drawn labels of the `*` atoms
SCAFFOLD_RAW = "C(*)(*)C<sep><a>1:R1</a><a>2:R2</a>"
ETHANOL = "CCO"
ETHANOL_OTHER = "OCC"  # same molecule, different text: canonical forms must match


class FakeReader:
    """Answers from a dict keyed by crop order; mimics benchmarks/readers.py Reader."""

    def __init__(self, name, answers, error=None):
        self.name, self.answers, self.error = name, answers, error
        self.versions = {name: "fake"}

    def predict(self, crops):
        if self.error:
            raise self.error
        return self.answers[: len(crops)] if self.answers is not None else []


def region(box_id, gate="molecule", crop=True):
    return {"paper_id": "7", "page": 1, "box_id": box_id, "x0": 0, "y0": 0, "x1": 10, "y1": 10,
            "crop_path": f"papers/7/crops/{box_id}.png" if crop else "", "role": "unknown", "gate": gate,
            "confidence": "", "reason": ""}


@pytest.fixture
def run_dir(tmp_path):
    """A one-paper front-end run: four readable regions and one rejected non-molecule."""
    (tmp_path / "papers" / "7" / "crops").mkdir(parents=True)
    regions = [region("7-p1-0"), region("7-p1-1"), region("7-p1-2"), region("7-p1-3", gate="uncertain"),
               region("7-p1-4", gate="non_molecule", crop=False)]
    write_csv(tmp_path / "papers" / "7" / "regions.csv", REGION_COLUMNS, regions)
    for r in regions:
        if r["crop_path"]:
            Image.new("RGB", (8, 8), "white").save(tmp_path / r["crop_path"])
    (tmp_path / "run.json").write_text(json.dumps({"task": "frontend"}), encoding="utf-8")
    return tmp_path


def answers(*smiles_raw):
    return [{"smiles": s, "confidence": 0.9, "raw": raw} for s, raw in smiles_raw]


def readers():
    glyph = FakeReader("molglyph", answers((ETHANOL, ETHANOL + "<sep>"), ("*C(*)C", SCAFFOLD_RAW),
                                           ("", ""), ("CCN", "CCN<sep>")))
    scribe = FakeReader("molscribe", answers((ETHANOL_OTHER, ETHANOL_OTHER), ("CC(C)C", "CC(C)C"),
                                             ("<invalid>", "<invalid>"), ("CCO", "CCO")))
    return [glyph, scribe]


def rows_by(rows):
    return {(r["box_id"], r["reader"]): r for r in rows}


# --- the consensus rule ---------------------------------------------------------------------------

def box(glyph, scribe):
    region_ = region("7-p1-0")
    return {name: reader_row(region_, name, p) for name, p in (("molglyph", glyph), ("molscribe", scribe)) if p}


def p(smiles, raw=None):
    return {"smiles": smiles, "confidence": 0.8, "raw": raw if raw is not None else smiles}


def test_agree_uses_the_primary_row_even_when_text_differs():
    row = consensus_row(box(p(ETHANOL, "G-RAW"), p(ETHANOL_OTHER, "S-RAW")))
    assert (row["reader"], row["status"], row["reason"]) == ("consensus", "ok", "agree")
    assert (row["smiles"], row["raw"]) == (ETHANOL, "G-RAW")


def test_disagree_keeps_molglyph_and_says_so():
    row = consensus_row(box(p("CCO", "G-RAW"), p("CCN", "S-RAW")))
    assert row["smiles"] == "CCO" and row["raw"] == "G-RAW"
    assert row["reason"] == "disagree: molglyph kept"


def test_molglyph_raw_labels_survive_into_consensus_when_scaffold_readings_differ():
    """The reason the stage exists: assembly needs MolGlyph's drawn R labels on the consensus row."""
    row = consensus_row(box(p("*C(*)C", SCAFFOLD_RAW), p("CC(C)C")))
    smiles, labels = labelled_scaffold(row)
    assert labels == {1: "R1", 2: "R2"} and smiles == "C(*)(*)C"


def test_second_reader_is_used_when_the_primary_abstains():
    row = consensus_row(box(p(""), p("CCN", "S-RAW")))
    assert (row["smiles"], row["raw"], row["status"]) == ("CCN", "S-RAW", "ok")
    assert row["reason"] == "molscribe only: molglyph abstain"


def test_unparsable_primary_falls_through_to_the_second_reader():
    row = consensus_row(box(p("C(("), p("CCN")))
    assert row["smiles"] == "CCN"


def test_both_abstain_gives_an_abstention_without_smiles():
    row = consensus_row(box(p(""), p("<invalid>")))
    assert (row["status"], row["smiles"], row["raw"]) == ("abstain", "", "")


def test_a_failed_reader_with_no_other_answer_is_an_error_not_an_abstention():
    rows = {"molglyph": error_row(region("7-p1-0"), "molglyph", "boom"),
            "molscribe": reader_row(region("7-p1-0"), "molscribe", p(""))}
    assert consensus_row(rows)["status"] == "error"


def test_canonical_ignores_atom_order_and_rejects_garbage():
    assert canonical("OCC") == canonical("CCO")
    assert canonical("C((") is None and canonical("") is None and canonical(None) is None


# --- the stage on a run folder --------------------------------------------------------------------

def test_one_row_per_box_and_reader_plus_a_consensus_row(run_dir):
    paper_dir = run_dir / "papers" / "7"
    read_paper(run_dir, paper_dir, readers())
    rows = read_csv(paper_dir / "readings.csv")
    assert list(rows[0]) == READING_COLUMNS
    keys = [(r["box_id"], r["reader"]) for r in rows]
    assert len(keys) == len(set(keys)) == 4 * 3  # 4 readable boxes x (2 readers + consensus)
    assert not any(r["box_id"] == "7-p1-4" for r in rows)  # the rejected non-molecule is not read


def test_uncertain_regions_are_read_only_when_asked(run_dir):
    paper_dir = run_dir / "papers" / "7"
    read_paper(run_dir, paper_dir, [FakeReader("molglyph", answers((ETHANOL, ""), ("CCN", ""), ("", ""))),
                                    FakeReader("molscribe", answers((ETHANOL, ""), ("CCN", ""), ("", "")))],
               gates=("molecule",))
    assert "7-p1-3" not in {r["box_id"] for r in read_csv(paper_dir / "readings.csv")}


def test_abstentions_are_kept_and_select_reading_prefers_consensus(run_dir):
    paper_dir = run_dir / "papers" / "7"
    read_paper(run_dir, paper_dir, readers())
    by = rows_by(read_csv(paper_dir / "readings.csv"))
    assert by[("7-p1-2", "molglyph")]["status"] == "abstain"
    assert by[("7-p1-2", "molscribe")]["status"] == "abstain" and by[("7-p1-2", "molscribe")]["smiles"] == ""
    assert by[("7-p1-2", "consensus")]["status"] == "abstain"
    chosen = select_reading([r for r in by.values() if r["box_id"] == "7-p1-1"])
    assert chosen["reader"] == "consensus" and chosen["raw"] == SCAFFOLD_RAW


def test_a_reader_that_raises_gives_error_rows_and_an_error_stage(run_dir):
    glyph, scribe = readers()
    broken = FakeReader("molscribe", None, error=RuntimeError("weights missing"))
    info = read_run(run_dir, [glyph, broken])
    rows = read_csv(run_dir / "papers" / "7" / "readings.csv")
    assert {r["status"] for r in rows if r["reader"] == "molscribe"} == {"error"}
    assert "weights missing" in next(r["reason"] for r in rows if r["reader"] == "molscribe")
    assert info["status"] == "error"
    assert json.loads((run_dir / "run.json").read_text())["stages"]["read"]["status"] == "error"
    # MolGlyph's answers still reach the consensus rows
    assert rows_by(rows)[("7-p1-0", "consensus")]["smiles"] == ETHANOL


def test_a_wrong_result_count_is_an_error_not_a_silent_drop(run_dir):
    short = FakeReader("molscribe", answers((ETHANOL, "")))  # one answer for four crops
    read_run(run_dir, [readers()[0], short])
    rows = read_csv(run_dir / "papers" / "7" / "readings.csv")
    errors = [r for r in rows if r["reader"] == "molscribe"]
    assert len(errors) == 4 and {r["status"] for r in errors} == {"error"}
    assert "1 results for 4 crops" in errors[0]["reason"]


def test_run_json_records_counts_versions_and_creates_empty_links(run_dir):
    info = read_run(run_dir, readers(), versions={"molglyph": "fake"})
    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["stages"]["read"]["status"] == "complete" == info["status"]
    assert meta["stages"]["read"]["versions"] == {"molglyph": "fake"}
    # boxes 0 agree; boxes 1 and 3 disagree; box 2 abstains and is counted in neither
    assert info["counts"]["consensus_agree"] == 1 and info["counts"]["consensus_disagree"] == 2
    assert (run_dir / "papers" / "7" / "links.jsonl").read_text() == ""


def test_existing_links_are_not_overwritten(run_dir):
    links = run_dir / "papers" / "7" / "links.jsonl"
    links.write_text('{"link_id": "x"}\n', encoding="utf-8")
    read_run(run_dir, readers())
    assert links.read_text() == '{"link_id": "x"}\n'


def test_main_returns_nonzero_when_the_stage_errored(run_dir):
    def loader(name, device="cpu"):
        return FakeReader(name, None, error=RuntimeError("no GPU")) if name == "molscribe" else readers()[0]

    assert main([str(run_dir)], loader=loader) == 1
    assert main([str(run_dir)], loader=lambda name, device="cpu": readers()[READERS.index(name)]) == 0
