"""Link compound labels such as 12a to drawings and R-group table rows.

Reads one paper's stage files (text.jsonl, regions.csv, tables.jsonl and
readings.csv) and writes links.jsonl, as set out in pipeline/INTERFACES.md
(contract 0.1). The rules use box positions only:

1. A label is a text block whose whole text is one compound label, such as
   12a, 7, NR-7h or (3). The text can come from the PDF or from OCR.
2. A row of an R-group table (one with an R column) links to the table's
   scaffold: the front end's scaffold_box_id if it is set, otherwise the
   closest scaffold above the table on the same page. A drawing inside a
   table cell links to its row.
3. Every other drawing takes the closest label just below it, or just above
   it if there is none below. No label, two equally close labels, or a label
   that a closer drawing already took give an abstention.
4. A row of an activity table (no R column, such as an IC50 table) names a
   compound shown elsewhere. It links to the drawing that got the same label
   in step 3, or abstains.
5. Non-molecule regions get no link, and text inside a table is never used
   as a drawing's label.

If the paper folder also holds ocr_text.jsonl (text.jsonl records with
source=ocr, from pipeline/ocr_text.py), those lines are used as labels too.

    python -m pipeline.linking data/pipeline_runs/<run_id>/papers/<paper_id>

AI disclosure: Claude Code wrote this first version and its tests at Jin's
request, for team review.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from pipeline.substituents import column_position

LINK_COLUMNS = "paper_id link_id box_id label table_id row_id evidence_block_ids status reason".split()
# One compound label, optionally in brackets: 12a, 7, NR-7h, S3, (14b).
LABEL = re.compile(r"[(\[]?([A-Za-z]{0,4}[-_]?\d{1,4}[a-z]{0,2}'?)[)\]]?")
# Text shaped like a label that names something else: a protein or kinase
# (MKK4, NTRK1: three or more capitals before the number), an amino-acid
# residue (Glu179) or an atom group drawn in a structure (NH2, CH3, SO2).
NOT_A_LABEL = re.compile(
    r"[A-Z]{3,}\d+[a-z]?"
    r"|(?:Ala|Arg|Asn|Asp|Cys|Gln|Glu|Gly|His|Ile|Leu|Lys|Met|Phe|Pro|Ser|Thr|Trp|Tyr|Val)\d+"
    r"|(?:NH|CH|OH|SH|CF|SO|NO|CO)\d"
    r"|R\d+[a-z]?")  # an R-group position (R1, R2a), not a compound
MAX_GAP = 0.6     # farthest a label may sit from its drawing, in drawing heights
TIE = 0.1          # two labels closer in score than this are a tie
TABLE_TIE_PT = 10  # two scaffolds closer to a table than this (points) are a tie


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def as_label(text: str) -> str | None:
    """Return the label if the whole text is one compound label, else None."""
    match = LABEL.fullmatch(text.strip())
    if not match or NOT_A_LABEL.fullmatch(match.group(1)):
        return None
    return match.group(1)


def bounds(record: dict) -> tuple[float, float, float, float]:
    return tuple(float(record[key]) for key in ("x0", "y0", "x1", "y1"))


def label_distance(drawing: tuple, label: tuple) -> tuple[float, str] | None:
    """Score where a label sits relative to a drawing; lower is closer.

    The label must overlap the drawing sideways and sit just below it (or in
    its lower half), or just above it. The score is the gap in drawing
    heights plus the sideways offset in drawing widths. Labels above score
    1.5 times worse, since papers usually put the label below. Returns
    (score, "below" or "above"), or None if the label is out of range.
    """
    x0, y0, x1, y1 = drawing
    lx0, ly0, lx1, ly1 = label
    if lx1 < x0 or lx0 > x1:
        return None
    height, width = max(y1 - y0, 1.0), max(x1 - x0, 1.0)
    offset = abs((lx0 + lx1) / 2 - (x0 + x1) / 2) / width
    below, above = ly0 - y1, y0 - ly1
    if -0.5 * height <= below <= MAX_GAP * height:
        return max(below, 0.0) / height + offset, "below"
    if 0 <= above <= MAX_GAP * height:
        return 1.5 * (above / height + offset), "above"
    return None


def new_link(paper_id: str, box_id: str | None, label: str | None, evidence: list[str],
             status: str, reason: str, table_id: str | None = None,
             row_id: str | None = None) -> dict:
    """One links.jsonl record; link_id is filled in by link_paper."""
    return {"paper_id": paper_id, "link_id": None, "box_id": box_id, "label": label,
            "table_id": table_id, "row_id": row_id, "evidence_block_ids": evidence,
            "status": status, "reason": reason}


def find_scaffold(table: dict, drawings: dict[str, dict],
                  scaffolds: set[str]) -> tuple[str | None, str, str]:
    """Pick a table's scaffold region, as (box_id, status, reason)."""
    given = table.get("scaffold_box_id")
    if given:
        if given in drawings:
            return given, "ok", "scaffold given by the front end"
        return None, "error", f"scaffold_box_id {given} is not a molecule region"
    x0, y0, x1, _ = table["bbox"]
    # A scaffold may overlap the top of the table by a few points.
    found = sorted(
        (y0 - float(region["y1"]), box_id) for box_id, region in drawings.items()
        if box_id in scaffolds and int(region["page"]) == int(table["page"])
        and float(region["y1"]) <= y0 + 5
        and float(region["x1"]) >= x0 and float(region["x0"]) <= x1)
    if not found:
        return None, "abstain", "no scaffold above the table on its page"
    if len(found) > 1 and found[1][0] - found[0][0] < TABLE_TIE_PT:
        return None, "abstain", f"two scaffolds equally close: {found[0][1]}, {found[1][1]}"
    return found[0][1], "ok", "closest scaffold above the table"


ACTIVITY_REASON = "activity table row: no drawing has this label"


def is_rgroup_table(table: dict) -> bool:
    """True if a column heading names an R position (R, R1, Ra), as assembly reads it."""
    return any(column_position(column.get("heading") or "")[0] for column in table["columns"])


def link_activity_rows(links: list[dict]) -> None:
    """Point each activity-table row at the drawing that has the same label."""
    by_label = {}
    for link in links:
        if link["status"] == "ok" and not link["row_id"]:
            by_label.setdefault(link["label"], []).append(link)
    for link in links:
        if link["reason"] != ACTIVITY_REASON:
            continue
        label = as_label((link["label"] or "").split(" (")[0])
        found = by_label.get(label, []) if label else []
        if not label:
            link["reason"] = "row has no compound label"
        elif len(found) == 1:
            link.update(box_id=found[0]["box_id"], status="ok",
                        reason="drawing with the same label",
                        evidence_block_ids=sorted(set(link["evidence_block_ids"])
                                                  | set(found[0]["evidence_block_ids"])))
        elif found:
            link["reason"] = f"two drawings have label {label}: " + ", ".join(f["box_id"] for f in found)


def link_tables(paper_id: str, tables: list[dict], drawings: dict[str, dict],
                scaffolds: set[str]) -> tuple[list[dict], set[str]]:
    """Link each table row to its scaffold, and drawn substituents to their row.

    Returns the links and the box IDs they used, so those drawings are not
    also given a label of their own. Tables the front end did not mark ok are
    skipped.
    """
    links, used = [], set()
    for table in tables:
        if table["status"] != "ok":
            continue
        if not is_rgroup_table(table):
            # Activity table: link_paper links its rows once drawings have labels.
            for row in table["rows"]:
                evidence = sorted({block for cell in row["cells"] for block in cell["evidence_block_ids"]})
                links.append(new_link(paper_id, None, row["label"], evidence, "abstain",
                                      ACTIVITY_REASON, table_id=table["table_id"], row_id=row["row_id"]))
            continue
        scaffold, status, reason = find_scaffold(table, drawings, scaffolds)
        if scaffold:
            used.add(scaffold)
        for row in table["rows"]:
            ids = {"table_id": table["table_id"], "row_id": row["row_id"]}
            evidence = sorted({block for cell in row["cells"] for block in cell["evidence_block_ids"]})
            if not row["label"]:
                links.append(new_link(paper_id, scaffold, None, evidence, "abstain",
                                      "row has no label", **ids))
                continue
            links.append(new_link(paper_id, scaffold, row["label"], evidence, status, reason, **ids))
            for cell in row["cells"]:
                if cell["box_id"]:
                    used.add(cell["box_id"])
                    links.append(new_link(paper_id, cell["box_id"], row["label"], evidence, "ok",
                                          f"drawn substituent in row {row['row_id']}", **ids))
    return links, used


def link_drawings(paper_id: str, drawings: dict[str, dict], labels: list[dict]) -> list[dict]:
    """Give each drawing the closest label below (or above) it, or abstain."""
    links, choices = {}, []
    for box_id, region in drawings.items():
        found = []
        for block in labels:
            if int(block["page"]) == int(region["page"]):
                scored = label_distance(bounds(region), bounds(block))
                if scored:
                    found.append((*scored, block))
        found.sort(key=lambda item: item[0])
        if not found:
            links[box_id] = new_link(paper_id, box_id, None, [], "abstain", "no label near the drawing")
        elif len(found) > 1 and found[1][0] - found[0][0] < TIE:
            names = ", ".join(as_label(block["text"]) for _, _, block in found[:2])
            links[box_id] = new_link(paper_id, box_id, None, [block["block_id"] for _, _, block in found[:2]],
                                     "abstain", f"two labels equally close: {names}")
        else:
            choices.append((box_id, *found[0]))
    # Each label goes to the drawing it is closest to.
    owner = {}
    for box_id, _, side, block in sorted(choices, key=lambda item: item[1]):
        label = as_label(block["text"])
        if block["block_id"] in owner:
            links[box_id] = new_link(paper_id, box_id, None, [block["block_id"]], "abstain",
                                     f"label {label} is closer to {owner[block['block_id']]}")
        else:
            owner[block["block_id"]] = box_id
            links[box_id] = new_link(paper_id, box_id, label, [block["block_id"]], "ok",
                                     f"closest label {side} the drawing")
    return [links[box_id] for box_id in drawings]


def link_paper(paper_dir: Path) -> list[dict]:
    """Return the links.jsonl records for one papers/<paper_id>/ folder.

    All four input files must exist (empty files are fine); a missing file
    raises FileNotFoundError rather than giving an empty, successful run.
    """
    paper_id = paper_dir.name
    blocks = read_jsonl(paper_dir / "text.jsonl")
    if (paper_dir / "ocr_text.jsonl").is_file():
        for block in read_jsonl(paper_dir / "ocr_text.jsonl"):
            # OCR often reads the digit 1 as l or I next to other digits (1la for 11a).
            block["text"] = re.sub(r"(?<=\d)[lI]|[lI](?=\d)", "1", block["text"])
            blocks.append(block)
    regions = read_csv(paper_dir / "regions.csv")
    tables = read_jsonl(paper_dir / "tables.jsonl")
    readings = read_csv(paper_dir / "readings.csv")
    drawings = {region["box_id"]: region for region in regions if region["gate"] != "non_molecule"}
    scaffolds = {box_id for box_id, region in drawings.items() if region["role"] == "scaffold"}
    scaffolds |= {reading["box_id"] for reading in readings
                  if reading["status"] == "ok" and "*" in reading["smiles"]}
    table_text = {block for table in tables for row in table["rows"]
                  for cell in row["cells"] for block in cell["evidence_block_ids"]}
    table_links, used = link_tables(paper_id, tables, drawings, scaffolds)
    labels = [block for block in blocks
              if block["block_id"] not in table_text and as_label(block["text"])]
    free = {box_id: region for box_id, region in drawings.items() if box_id not in used}
    links = link_drawings(paper_id, free, labels) + table_links
    link_activity_rows(links)
    for number, link in enumerate(links, start=1):
        link["link_id"] = f"{paper_id}-link{number}"
    return links


def main() -> None:
    parser = argparse.ArgumentParser(description="Link compound labels to drawings and table rows.")
    parser.add_argument("paper_dir", type=Path, help="a run's papers/<paper_id>/ folder")
    args = parser.parse_args()
    links = link_paper(args.paper_dir)
    write_jsonl(args.paper_dir / "links.jsonl", links)
    ok = sum(link["status"] == "ok" for link in links)
    print(f"Wrote {len(links)} links ({ok} ok, {len(links) - ok} abstain or error) "
          f"to {args.paper_dir / 'links.jsonl'}")


if __name__ == "__main__":
    main()
