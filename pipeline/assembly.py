"""R-group assembly: build one full molecule per table row from a scaffold and its substituents.

Reads one paper's `tables.jsonl`, `links.jsonl` and `readings.csv` and writes
`assemblies.jsonl`, with the fields in pipeline/INTERFACES.md (contract 0.1).
For every row of every R-group table:

1. Find the row's scaffold: the drawing that label linking tied to the row.
2. Find what fills each position: one cell per R-group column, plus ring-atom
   columns (A, B) when the scaffold reading labels a `*` with that heading. A
   cell holds text (`OMe` or the linker `SO2`, looked up in substituents.py), a
   drawing (a `box_id` whose reading has one `*`) or a ring atom (`-N=`).
3. Decide which cell goes on which `*` of the scaffold. Three cases are
   unambiguous: the reader's star labels match the headings (`Ra` and `R[a]`),
   the points are numbered (`[1*]`, `[2*]`) and the columns match (R1, R2), or
   there is one point and one column.
4. Set ring atoms, bond the pieces with RDKit's `molzip` and write the canonical SMILES.

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

from pipeline.stage_io import (DEFAULT_READERS, attachment_points, labelled_scaffold, paper_dirs,
                               parse_smiles,
                               read_jsonl, readings_by_box, select_reading, update_stage,
                               write_jsonl)
from pipeline.substituents import (column_position, linker_fragment, ring_atom, same_label,
                                   text_fragment)

METHOD = "r_group_assembly"


class Abstain(Exception):
    """This row cannot be assembled with certainty; the message is the recorded reason."""


def match_positions(scaffold: Chem.Mol, positions: list[int | None],
                    headings: list[str] | None = None, labels: dict[int, str] | None = None) -> list[int]:
    """Choose the scaffold `*` atom for each table column, or abstain.

    `positions` holds each R column's number (1 for R1) or None for an
    unnumbered heading such as R or Ra. Returns one atom index per column.
    When the reader kept each `*`'s drawn label (`labels`, atom index to label),
    columns are matched to stars by name (`Ra` to `R[a]`, `A` to `A`) first.
    """
    points = attachment_points(scaffold)
    if labels and headings:
        matched = []
        for heading in headings:
            hits = [atom.GetIdx() for atom in points if same_label(heading, labels.get(atom.GetIdx(), ""))]
            if len(hits) != 1:
                break
            matched.append(hits[0])
        else:
            if len(set(matched)) == len(matched):
                return matched
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


RING = "ring:"  # a piece that replaces an in-ring `*` with an atom: "ring:N" or "ring:C:*Cl"


def _split_linker_point(mol: Chem.RWMol, index: int) -> int:
    """Give a two-neighbour `*` a twin, one per neighbour, so a linker can bond to both.

    Returns the twin's index. The star must not be in a ring (that would be a
    ring atom, not a linker) and both bonds must be single.
    """
    star = mol.GetAtomWithIdx(index)
    bonds = list(star.GetBonds())
    if star.IsInRing() or len(bonds) != 2 or any(b.GetBondType() != Chem.BondType.SINGLE for b in bonds):
        raise Abstain("linker position is not a two-neighbour chain atom")
    other = bonds[1].GetOtherAtomIdx(index)
    twin = mol.AddAtom(Chem.Atom(0))
    mol.RemoveBond(index, other)
    mol.AddBond(twin, other, Chem.BondType.SINGLE)
    return twin


def join(scaffold_smiles: str, pieces: list[tuple[int | None, str]],
         headings: list[str] | None = None, labels: dict[int, str] | None = None) -> str:
    """Fill a scaffold's `*` atoms from the table and return canonical SMILES.

    `pieces` is a list of (R number or None, piece), where a piece is a fragment
    SMILES with one `*` (a substituent), two `*` (a linker; its scaffold `*`
    must sit between two atoms) or `ring:<element>[:<fragment>]` (a ring atom
    replacing an in-ring `*`). `headings` and `labels` let columns be matched to
    stars by their drawn labels (see match_positions). Each pair of `*` atoms
    that should meet gets the same atom-map number, and `molzip` replaces the
    pair with a bond. Raises Abstain if the result is not one complete, valid molecule.
    """
    scaffold = parse_smiles(scaffold_smiles)
    if scaffold is None:
        raise Abstain("scaffold reading is not valid SMILES")
    if not attachment_points(scaffold):
        raise Abstain("scaffold reading has no attachment point")
    targets = match_positions(scaffold, [position for position, _ in pieces], headings, labels)

    combined = Chem.RWMol(scaffold)
    for atom in attachment_points(combined):
        atom.SetAtomMapNum(0)
    bonds: list[tuple[list[int], str]] = []  # (scaffold star indices, fragment) pairs to zip
    # Ring atoms and linker twins only change or append atoms, so `targets` stays valid.
    for index, (_, piece) in zip(targets, pieces):
        star = combined.GetAtomWithIdx(index)
        if piece.startswith(RING):
            element, _, fragment = piece[len(RING):].partition(":")
            if not star.IsInRing():
                raise Abstain("ring-atom column fills a star that is not in a ring")
            star.SetAtomicNum(Chem.GetPeriodicTable().GetAtomicNumber(element))
            star.SetIsotope(0)
            star.SetNumExplicitHs(0)
            star.SetNoImplicit(False)
            if fragment:
                handle = combined.AddAtom(Chem.Atom(0))
                combined.AddBond(index, handle, Chem.BondType.SINGLE)
                bonds.append(([handle], fragment))
            continue
        fragment = parse_smiles(piece)
        points = len(attachment_points(fragment)) if fragment is not None else 0
        if points == 2 and star.GetDegree() == 2:
            bonds.append(([index, _split_linker_point(combined, index)], piece))
        elif points == 1 and star.GetDegree() == 1:
            bonds.append(([index], piece))
        elif points == 2:
            raise Abstain(f"linker {piece!r} fills an end position")
        else:
            raise Abstain(f"substituent {piece!r} is not a one-point fragment"
                          if star.GetDegree() == 1 else
                          f"substituent {piece!r} fills a position between two atoms")
    number = 0
    for stars, piece in bonds:
        fragment = parse_smiles(piece)
        ends = attachment_points(fragment)
        for star_index, end in zip(stars, ends):
            number += 1
            for atom in (combined.GetAtomWithIdx(star_index), end):
                atom.SetAtomMapNum(number)
                atom.SetIsotope(0)
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
    raise Abstain(("link abstained: " + reasons[0]) if reasons else "no scaffold is linked to this row")


def read_cell(cell: dict | None, heading: str, readings: dict[str, list[dict]],
              readers: tuple[str, ...], ring_column: bool = False) -> tuple[dict, str | None]:
    """Interpret one table cell that fills a scaffold position. Returns its record and a problem, if any.

    A substituent cell holds text (a one-point group, or a two-point linker such
    as SO2) or a drawing. A ring-atom cell (`ring_column`, paper 19's A and B)
    names the atom itself. The record keeps the cell text and how it was read,
    so a wrong molecule can be traced back to the cell that caused it.
    """
    record = {"column_id": cell["column_id"] if cell else None, "heading": heading,
              "cell_id": cell.get("cell_id") if cell else None,
              "text": cell.get("text") if cell else None,
              "box_id": cell.get("box_id") if cell else None, "kind": None, "fragment": None}
    if cell is None:
        return record, f"row has no cell in column {heading}"
    if ring_column:
        record["kind"] = "ring_atom"
        atom = ring_atom(cell.get("text") or "")
        if atom is None:
            return record, f"ring-atom text {cell.get('text')!r} in column {heading} is not recognised"
        record["fragment"] = RING + atom[0] + (":" + atom[1] if atom[1] else "")
        return record, None
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
        record["fragment"] = linker_fragment(cell["text"])
        record["kind"] = "linker" if record["fragment"] else "text"
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
        cells = {cell["column_id"]: cell for cell in row["cells"]}
        scaffold_box = None
        reading, scaffold_smiles, labels = None, None, {}
        try:
            scaffold_box = find_scaffold(table, row, row_links)
        except Abstain as no_scaffold:
            scaffold_problem = str(no_scaffold)
        else:
            scaffold_problem = None
            reading = select_reading(readings.get(scaffold_box, []), readers)
            if reading is not None and reading["status"] == "ok":
                scaffold_smiles, labels = labelled_scaffold(reading)
        # R columns always fill a position. Any other column fills one only when
        # the scaffold reading labels a star with its heading (A, B): a ring atom.
        columns = []
        for column in table["columns"]:
            heading = column.get("heading") or ""
            is_r, position = column_position(heading)
            if is_r:
                columns.append((column, position, False))
            elif any(same_label(heading, label) for label in labels.values()):
                columns.append((column, None, True))
        # Evidence is the label cell, the filling cells and whatever linking used;
        # activity columns (IC50 and so on) played no part in the molecule.
        used = {column["column_id"] for column, _, _ in columns}
        record["evidence_block_ids"] = _unique(
            [b for cell in row["cells"] for b in cell.get("evidence_block_ids") or []
             if cell["column_id"] in used or (cell.get("text") or "").strip() == record["label"]]
            + [b for link in row_links for b in link.get("evidence_block_ids") or []])
        problems = []
        for column, _, ring_column in columns:
            entry, problem = read_cell(cells.get(column["column_id"]), column["heading"], readings, readers,
                                       ring_column)
            record["substituents"].append(entry)
            if problem:
                problems.append(problem)

        if scaffold_problem:
            raise Abstain(scaffold_problem)
        record["scaffold_box_id"] = scaffold_box
        record["source_box_ids"] = _unique([scaffold_box] + [s["box_id"] for s in record["substituents"]])
        if not columns:
            raise Abstain("table has no R-group column")
        if problems:
            raise Abstain("; ".join(problems))
        if scaffold_smiles is None:
            raise Abstain("scaffold has no reading")
        pieces = [(position, entry["fragment"])
                  for (_, position, _), entry in zip(columns, record["substituents"])]
        record["smiles"] = join(scaffold_smiles, pieces,
                                [column["heading"] for column, _, _ in columns], labels)
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
