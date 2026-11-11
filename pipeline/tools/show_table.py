"""Print one table of a front-end run: caption, headings, every row and cell, footnote and scaffold.

Usage (from the repo root):
    uv run python pipeline/tools/show_table.py data/pipeline_runs/<run> 1 7        # paper 1, page 7
    uv run python pipeline/tools/show_table.py data/pipeline_runs/<run> 2 5 2      # paper 2, page 5, second table on it

Reads <run>/papers/<paper>/tables.jsonl; writes nothing.
AI disclosure: Claude (Anthropic) drafted this helper for Peter Adranly.
"""
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) not in (4, 5):
        print(__doc__)
        return 2
    run, paper, page = Path(argv[1]), argv[2], int(argv[3])
    which = int(argv[4]) if len(argv) == 5 else 1
    path = run / "papers" / paper / "tables.jsonl"
    if not path.is_file():
        print(f"{path} not found")
        return 1
    tables = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    found = [t for t in tables if t["page"] == page]
    if len(found) < which:
        print(f"paper {paper} page {page}: {len(found)} table(s) found")
        return 1
    t = found[which - 1]
    print(f"{t['table_id']}  status={t['status']}  bbox={t['bbox']}  scaffold={t['scaffold_box_id']}")
    print("caption:", (t.get("caption") or "-").replace("\n", " "))
    if t["reason"]:
        print("reason: ", t["reason"])
    print("headings:", [(c["heading"] or "-").replace("\n", " ") for c in t["columns"]])
    for row in t["rows"]:
        print(f"  {row['row_id']:>4}", [c["text"].replace("\n", " ") for c in row["cells"]])
    print("notes:", t.get("notes") or "-")
    drawings = [c["box_id"] for r in t["rows"] for c in r["cells"] if c["box_id"]]
    print(f"rows: {len(t['rows'])} | cells holding a drawing: {len(drawings)} {drawings[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
