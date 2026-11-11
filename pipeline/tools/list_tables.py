"""List every table of a front-end run, with its status and reason, and flag caption-like text the method missed.

Usage (from the repo root):
    uv run python pipeline/tools/list_tables.py data/pipeline_runs/frontend-captions
    uv run python pipeline/tools/list_tables.py data/pipeline_runs/frontend-captions 4 19      # only these papers

Reads <run>/papers/<id>/tables.jsonl and text.jsonl; writes nothing.
AI disclosure: Claude (Anthropic) drafted this helper for Peter Adranly.
"""
import json
import re
import sys
from pathlib import Path

CAPTION_TABLE = re.compile(r"^\s*Table\s+S?\d+\.")          # what the caption method looks for
CAPTION_LIKE = re.compile(r"^\s*Table\s+\S+", re.IGNORECASE)  # anything that looks like a table caption


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    papers_dir = Path(argv[1]) / "papers"
    if not papers_dir.is_dir():
        print(f"{papers_dir} not found")
        return 1
    wanted = set(argv[2:])
    scaffolds, tables_total, built = set(), 0, 0
    for paper_dir in sorted(papers_dir.iterdir(), key=lambda p: (len(p.name), p.name)):
        if wanted and paper_dir.name not in wanted:
            continue
        tables = read_jsonl(paper_dir / "tables.jsonl")
        blocks = read_jsonl(paper_dir / "text.jsonl")
        print(f"\npaper {paper_dir.name}: {len(tables)} tables")
        for t in tables:
            tables_total += 1
            built += t["status"] == "ok"
            if t.get("scaffold_box_id"):
                scaffolds.add((paper_dir.name, t["scaffold_box_id"]))
            caption = (t.get("caption") or "-").replace("\n", " ")[:46]
            print(f"  p{t['page']:<2} {t['status']:7} {len(t['rows']):>2} rows x {len(t['columns']):>2} cols"
                  f" | scaffold {t.get('scaffold_box_id') or '-':9} | {caption!r}")
            if t["reason"]:
                print(f"        reason: {t['reason'][:100]}")
        found = {(t["page"], (t.get("caption") or "")[:12]) for t in tables}
        missed = [b for b in blocks if CAPTION_LIKE.match(b["text"]) and not CAPTION_TABLE.match(b["text"])]
        for b in missed[:6]:
            print(f"  possible caption NOT matched (page {b['page']}): {b['text'][:60].strip()!r}")
    print(f"\ntotal: {tables_total} tables, {built} ok, {len(scaffolds)} distinct scaffold drawings linked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
