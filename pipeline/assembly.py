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

Steps 1 and 2 (which drawing and which cells belong to a row) are in this file.
Steps 3 and 4 (the RDKit work) are in join.py.

Any step that cannot be done with certainty makes the row an abstention with a
reason, and no SMILES. Joining pieces on a guess is the main risk of this
stage: on the six internal papers, blind same-page pairing gives 582 candidate
molecules for 17 right ones (reports/1.4-group-report/assembly_example.py).

    python -m pipeline.assembly data/pipeline_runs/<run_id>

AI disclosure: Claude Code wrote this file at Will's request, for his review,
and on Nov 17 split its long functions into the smaller helpers below.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from pipeline.stage_io import (DEFAULT_READERS, attachment_points, labelled_scaffold, paper_dirs,
                               parse_smiles,
                               read_jsonl, readings_by_box, select_reading, update_stage,
                               write_jsonl)
from pipeline.join import RING, Abstain, join
from pipeline.substituents import (column_position, linker_fragment, ring_atom, same_label,
                                   text_fragment)

METHOD = "r_group_assembly"


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


def _read_ring_cell(record: dict, cell: dict, heading: str) -> str | None:
    """A ring-atom cell (paper 19's A and B columns) names the atom itself, such as `-N=`."""
    record["kind"] = "ring_atom"
    atom = ring_atom(cell.get("text") or "")
    if atom is None:
        return f"ring-atom text {cell.get('text')!r} in column {heading} is not recognised"
    record["fragment"] = RING + atom[0] + (":" + atom[1] if atom[1] else "")
    return None


def _read_drawn_cell(record: dict, cell: dict, heading: str, readings: dict[str, list[dict]],
                     readers: tuple[str, ...]) -> str | None:
    """A drawn substituent: use its reading, which must have exactly one `*`."""
    record["kind"] = "drawing"
    reading = select_reading(readings.get(cell["box_id"], []), readers)
    if reading is None or reading["status"] != "ok":
        return f"drawn substituent in column {heading} has no reading"
    fragment = parse_smiles(reading["smiles"])
    points = len(attachment_points(fragment)) if fragment is not None else 0
    if points != 1:
        return f"drawn substituent in column {heading} has {points} attachment points, not 1"
    record["fragment"] = reading["smiles"]
    return None


def _read_text_cell(record: dict, cell: dict, heading: str) -> str | None:
    """A text cell: a one-point group (`OMe`) or a two-point linker (`SO2`), from substituents.py."""
    if not (cell.get("text") or "").strip():
        return f"empty cell in column {heading}"
    record["kind"] = "text"
    record["fragment"] = text_fragment(cell["text"])
    if record["fragment"] is None:
        record["fragment"] = linker_fragment(cell["text"])
        record["kind"] = "linker" if record["fragment"] else "text"
    if record["fragment"] is None:
        return f"substituent text {cell['text']!r} in column {heading} is not in the abbreviation table"
    return None


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
        return record, _read_ring_cell(record, cell, heading)
    if cell.get("box_id"):
        return record, _read_drawn_cell(record, cell, heading, readings, readers)
    return record, _read_text_cell(record, cell, heading)


def _empty_record(table: dict, row: dict, row_links: list[dict]) -> dict:
    """A new `assemblies.jsonl` record for one row, marked as an abstention until assembly succeeds."""
    return {
        "paper_id": table["paper_id"], "assembly_id": None, "scaffold_box_id": None,
        "table_id": table["table_id"], "row_id": row["row_id"],
        "label": row.get("label") or next((l["label"] for l in row_links if l.get("label")), None),
        "smiles": None, "source_box_ids": [], "evidence_block_ids": [],
        "method": METHOD, "status": "abstain", "reason": None, "substituents": [],
    }


def _scaffold_for_row(table: dict, row: dict, row_links: list[dict], readings: dict[str, list[dict]],
                      readers: tuple[str, ...]) -> tuple[str | None, str | None, dict[int, str], str | None]:
    """Find the row's scaffold and its reading.

    Returns (box_id, SMILES, star labels, problem). A missing scaffold is
    returned as a problem rather than raised, so the row's cells are still read
    and recorded before the row abstains. SMILES is None when the scaffold has
    no usable reading.
    """
    try:
        scaffold_box = find_scaffold(table, row, row_links)
    except Abstain as no_scaffold:
        return None, None, {}, str(no_scaffold)
    reading = select_reading(readings.get(scaffold_box, []), readers)
    if reading is None or reading["status"] != "ok":
        return scaffold_box, None, {}, None
    scaffold_smiles, labels = labelled_scaffold(reading)
    return scaffold_box, scaffold_smiles, labels, None


def _filling_columns(table: dict, labels: dict[int, str]) -> list[tuple[dict, int | None, bool]]:
    """The columns that fill a scaffold position, as (column, R number or None, is a ring-atom column).

    R columns always fill a position. Any other column fills one only when the
    scaffold reading labels a star with its heading (A, B): a ring atom.
    """
    columns = []
    for column in table["columns"]:
        heading = column.get("heading") or ""
        is_r, position = column_position(heading)
        if is_r:
            columns.append((column, position, False))
        elif any(same_label(heading, label) for label in labels.values()):
            columns.append((column, None, True))
    return columns


def _evidence_ids(row: dict, row_links: list[dict], used: set[str], label: str | None) -> list[str]:
    """Text blocks behind the row: the label cell, the filling cells and whatever linking used.

    Activity columns (IC50 and so on) played no part in the molecule, so they are left out.
    """
    return _unique(
        [b for cell in row["cells"] for b in cell.get("evidence_block_ids") or []
         if cell["column_id"] in used or (cell.get("text") or "").strip() == label]
        + [b for link in row_links for b in link.get("evidence_block_ids") or []])


def _read_columns(row: dict, columns: list[tuple[dict, int | None, bool]], readings: dict[str, list[dict]],
                  readers: tuple[str, ...], entries: list[dict]) -> list[str]:
    """Read each filling cell, appending its record to `entries`; returns the problems found."""
    cells = {cell["column_id"]: cell for cell in row["cells"]}
    problems = []
    for column, _, ring_column in columns:
        entry, problem = read_cell(cells.get(column["column_id"]), column["heading"], readings, readers,
                                   ring_column)
        entries.append(entry)
        if problem:
            problems.append(problem)
    return problems


def assemble_row(table: dict, row: dict, row_links: list[dict], readings: dict[str, list[dict]],
                 readers: tuple[str, ...] = DEFAULT_READERS) -> dict:
    """Assemble one table row into an `assemblies.jsonl` record (without its ID).

    The cells are read and recorded even when the row will abstain, so every
    abstention shows what the table held. The checks then run in a fixed order
    and the first one that fails becomes the recorded reason.
    """
    record = _empty_record(table, row, row_links)
    try:
        scaffold_box, scaffold_smiles, labels, scaffold_problem = _scaffold_for_row(
            table, row, row_links, readings, readers)
        columns = _filling_columns(table, labels)
        used = {column["column_id"] for column, _, _ in columns}
        record["evidence_block_ids"] = _evidence_ids(row, row_links, used, record["label"])
        problems = _read_columns(row, columns, readings, readers, record["substituents"])

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
