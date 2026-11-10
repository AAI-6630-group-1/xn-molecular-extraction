"""R-group assembly: build one full molecule per table row from a scaffold and its substituents.

Reads one paper's `tables.jsonl`, `links.jsonl` and `readings.csv` and writes
`assemblies.jsonl`, with the fields in pipeline/INTERFACES.md (contract 0.1).
For every row of every R-group table:

1. Find the row's scaffold: the drawing that label linking tied to the row.
2. Find the row's substituents: one per R-group column. A cell holds either
   text (`OMe`, looked up in substituents.py) or a drawing (a `box_id`, whose
   reading must be a fragment with one `*`).
3. Decide which substituent goes on which `*` of the scaffold. Only two cases
   are unambiguous: the scaffold's points are numbered (`[1*]`, `[2*]`) and the
   columns are numbered to match (R1, R2), or there is one point and one column.
4. Bond the pieces with RDKit's `molzip` and write the canonical SMILES.

Any step that cannot be done with certainty makes the row an abstention with a
reason, and no SMILES. Joining pieces on a guess is the main risk of this
stage: on the six internal papers, blind same-page pairing gives 582 candidate
molecules for 17 right ones (reports/1.4-group-report/assembly_example.py).

    python -m pipeline.assembly data/pipeline_runs/<run_id>

AI disclosure: Claude Code wrote this file at Will's request, for his review.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from rdkit import Chem

from pipeline.stage_io import (DEFAULT_READERS, attachment_points, paper_dirs, parse_smiles,
                               read_jsonl, readings_by_box, select_reading, update_stage,
                               write_jsonl)
from pipeline.substituents import column_position, text_fragment

METHOD = "r_group_assembly"


class Abstain(Exception):
    """This row cannot be assembled with certainty; the message is the recorded reason."""


def match_positions(scaffold: Chem.Mol, positions: list[int | None]) -> list[int]:
    """Choose the scaffold `*` atom for each substituent, or abstain.

    `positions` holds each R column's number (1 for R1) or None for an
    unnumbered heading such as R or X. Returns one atom index per column.
    """
    points = attachment_points(scaffold)
    numbers = [atom.GetIsotope() for atom in points]  # readers write R1 as [1*]
    numbered = all(numbers) and len(set(numbers)) == len(numbers)
    if numbered and all(position is not None for position in positions):
        if len(set(positions)) != len(positions):
            raise Abstain("two table columns name the same R position")
        missing = [f"R{p}" for p in positions if p not in numbers]
        if missing:
            raise Abstain(f"scaffold reading has no {', '.join(missing)}")
        return [points[numbers.index(p)].GetIdx() for p in positions]
    if len(points) == 1 and len(positions) == 1:
        return [points[0].GetIdx()]
    raise Abstain(f"cannot tell which column fills which attachment point "
                  f"({len(points)} points, {len(positions)} R columns, numbers do not match)")


def join(scaffold_smiles: str, pieces: list[tuple[int | None, str]]) -> str:
    """Bond substituent fragments onto a scaffold and return canonical SMILES.

    `pieces` is a list of (R number or None, fragment SMILES with one `*`).
    Each pair of `*` atoms that should meet gets the same atom-map number, and
    `molzip` replaces the pair with a bond. Raises Abstain if the result is not
    one complete, valid molecule.
    """
    scaffold = parse_smiles(scaffold_smiles)
    if scaffold is None:
        raise Abstain("scaffold reading is not valid SMILES")
    if not attachment_points(scaffold):
        raise Abstain("scaffold reading has no attachment point")
    targets = match_positions(scaffold, [position for position, _ in pieces])

    combined = Chem.RWMol(scaffold)
    for atom in attachment_points(combined):
        atom.SetAtomMapNum(0)
    for number, (index, (_, fragment_smiles)) in enumerate(zip(targets, pieces), start=1):
        fragment = parse_smiles(fragment_smiles)
        if fragment is None or len(attachment_points(fragment)) != 1:
            raise Abstain(f"substituent {fragment_smiles!r} is not a one-point fragment")
        for atom in (combined.GetAtomWithIdx(index), attachment_points(fragment)[0]):
            atom.SetAtomMapNum(number)
            atom.SetIsotope(0)
        # Appending keeps the scaffold's atom indices, so `targets` stays valid.
        combined = Chem.RWMol(Chem.CombineMols(combined, fragment))
    try:
        zipped = Chem.molzip(combined)
        # Re-parsing folds an explicit [H] substituent back into its neighbour.
        product = parse_smiles(Chem.MolToSmiles(zipped))
    except Exception as error:  # molzip and sanitization raise on impossible valences
        raise Abstain(f"joined pieces are not a valid molecule ({type(error).__name__})") from error
    if product is None:
        raise Abstain("joined pieces are not a valid molecule")
    unfilled = len(attachment_points(product))
    if unfilled:
        raise Abstain(f"{unfilled} attachment point(s) of the scaffold have no table column")
    return Chem.MolToSmiles(product)


def _unique(values) -> list:
    return list(dict.fromkeys(v for v in values if v))


def find_scaffold(table: dict, row: dict, row_links: list[dict]) -> str:
    """Return the box_id of the scaffold linked to a row, or abstain."""
    cell_boxes = {cell.get("box_id") for cell in row["cells"]}
    linked = _unique(link["box_id"] for link in row_links
                     if link["status"] == "ok" and link.get("box_id") not in cell_boxes)
    if len(linked) > 1:
        raise Abstain(f"row is linked to more than one scaffold: {', '.join(linked)}")
    if linked:
        return linked[0]
    if table.get("scaffold_box_id"):
        return table["scaffold_box_id"]
    reasons = _unique(link.get("reason") for link in row_links if link["status"] != "ok")
    raise Abstain("link abstained: " + reasons[0] if reasons else "no scaffold is linked to this row")


def read_cell(cell: dict | None, heading: str, readings: dict[str, list[dict]],
              readers: tuple[str, ...]) -> tuple[dict, str | None]:
    """Interpret one substituent cell. Returns its record and a problem, if any.

    The record keeps the cell text and how it was read, so a wrong molecule can
    be traced back to the cell that caused it.
    """
    record = {"column_id": cell["column_id"] if cell else None, "heading": heading,
              "cell_id": cell.get("cell_id") if cell else None,
              "text": cell.get("text") if cell else None,
              "box_id": cell.get("box_id") if cell else None, "kind": None, "fragment": None}
    if cell is None:
        return record, f"row has no cell in column {heading}"
    if cell.get("box_id"):
        record["kind"] = "drawing"
        reading = select_reading(readings.get(cell["box_id"], []), readers)
        if reading is None or reading["status"] != "ok":
            return record, f"drawn substituent in column {heading} has no reading"
        fragment = parse_smiles(reading["smiles"])
        points = len(attachment_points(fragment)) if fragment is not None else 0
        if points != 1:
            return record, f"drawn substituent in column {heading} has {points} attachment points, not 1"
        record["fragment"] = reading["smiles"]
        return record, None
    if not (cell.get("text") or "").strip():
        return record, f"empty cell in column {heading}"
    record["kind"] = "text"
    record["fragment"] = text_fragment(cell["text"])
    if record["fragment"] is None:
        return record, f"substituent text {cell['text']!r} in column {heading} is not in the abbreviation table"
    return record, None


def assemble_row(table: dict, row: dict, row_links: list[dict], readings: dict[str, list[dict]],
                 readers: tuple[str, ...] = DEFAULT_READERS) -> dict:
    """Assemble one table row into an `assemblies.jsonl` record (without its ID)."""
    record = {
        "paper_id": table["paper_id"], "assembly_id": None, "scaffold_box_id": None,
        "table_id": table["table_id"], "row_id": row["row_id"],
        "label": row.get("label") or next((l["label"] for l in row_links if l.get("label")), None),
        "smiles": None, "source_box_ids": [], "evidence_block_ids": [],
        "method": METHOD, "status": "abstain", "reason": None, "substituents": [],
    }
    try:
        columns = [(column, position) for column in table["columns"]
                   for is_r, position in [column_position(column.get("heading") or "")] if is_r]
        cells = {cell["column_id"]: cell for cell in row["cells"]}
        # Evidence is the label cell, the substituent cells and whatever linking used;
        # activity columns (IC50 and so on) played no part in the molecule.
        used = {column["column_id"] for column, _ in columns}
        record["evidence_block_ids"] = _unique(
            [b for cell in row["cells"] for b in cell.get("evidence_block_ids") or []
             if cell["column_id"] in used or (cell.get("text") or "").strip() == record["label"]]
            + [b for link in row_links for b in link.get("evidence_block_ids") or []])
        problems = []
        for column, _ in columns:
            entry, problem = read_cell(cells.get(column["column_id"]), column["heading"], readings, readers)
            record["substituents"].append(entry)
            if problem:
                problems.append(problem)

        scaffold_box = find_scaffold(table, row, row_links)
        record["scaffold_box_id"] = scaffold_box
        record["source_box_ids"] = _unique([scaffold_box] + [s["box_id"] for s in record["substituents"]])
        if not columns:
            raise Abstain("table has no R-group column")
        if problems:
            raise Abstain("; ".join(problems))
        reading = select_reading(readings.get(scaffold_box, []), readers)
        if reading is None or reading["status"] != "ok":
            raise Abstain("scaffold has no reading")
        pieces = [(position, entry["fragment"])
                  for (_, position), entry in zip(columns, record["substituents"])]
        record["smiles"] = join(reading["smiles"], pieces)
        record["status"] = "ok"
    except Abstain as abstention:
        record["reason"] = str(abstention)
    except Exception as error:  # a malformed record: keep the row, marked as a failure
        record["status"] = "error"
        record["reason"] = f"{type(error).__name__}: {error}"
    return record


def assemble_paper(paper_dir: Path, readers: tuple[str, ...] = DEFAULT_READERS) -> list[dict]:
    """Write `assemblies.jsonl` for one paper: one record per table row."""
    tables = read_jsonl(paper_dir / "tables.jsonl")
    links: dict[str, list[dict]] = {}
    for link in read_jsonl(paper_dir / "links.jsonl"):
        if link.get("row_id"):
            links.setdefault(link["row_id"], []).append(link)
    readings = readings_by_box(paper_dir)
    records = []
    for table in tables:
        for row in table.get("rows") or []:
            record = assemble_row(table, row, links.get(row["row_id"], []), readings, readers)
            record["assembly_id"] = f"{table['paper_id']}-asm{len(records) + 1}"
            records.append(record)
    write_jsonl(paper_dir / "assemblies.jsonl", records)
    return records


def assemble_run(run_dir: Path, readers: tuple[str, ...] = DEFAULT_READERS) -> dict:
    """Assemble every paper of a run and record the counts in run.json."""
    records = [r for paper_dir in paper_dirs(run_dir) for r in assemble_paper(paper_dir, readers)]
    statuses = Counter(r["status"] for r in records)
    info = {"status": "complete", "records": len(records),
            "ok": statuses["ok"], "abstain": statuses["abstain"], "error": statuses["error"],
            "abstain_reasons": dict(Counter(r["reason"] for r in records if r["status"] == "abstain")),
            "readers": list(readers)}
    update_stage(run_dir, "assemble", info)
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("run_dir", type=Path, help="a folder under data/pipeline_runs/")
    parser.add_argument("--readers", nargs="+", default=list(DEFAULT_READERS),
                        help="reader preference order for choosing one reading per box")
    args = parser.parse_args()
    info = assemble_run(args.run_dir, tuple(args.readers))
    print(f"{info['records']} table rows: {info['ok']} assembled, "
          f"{info['abstain']} abstained, {info['error']} errors")


if __name__ == "__main__":
    main()
