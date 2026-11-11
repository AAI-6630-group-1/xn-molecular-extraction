"""Explain why a table came out with no headings or rows: the rules found, the words in its area, and which detected
molecule boxes swallowed them.

Usage (from the repo root):
    uv run python pipeline/tools/explain_table.py data/pipeline_runs/<run> 2 5        # paper 2, page 5
    uv run python pipeline/tools/explain_table.py data/pipeline_runs/<run> 1 7 1      # paper 1, page 7, first table on it

Reads the run's tables.jsonl, regions.csv and text.jsonl plus data/internal/<paper>.pdf; writes nothing.
AI disclosure: Claude (Anthropic) drafted this helper for Peter Adranly; it was tested with a fake page first.
"""
import csv
import json
import sys
from pathlib import Path


def rect_tuple(rect) -> tuple:
    return (rect.x0, rect.y0, rect.x1, rect.y1)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def describe(frontend, page, page_no: int, record: dict, blocks: list[dict], regions: list[dict]) -> list[str]:
    prefix = " ".join((record.get("caption") or "").split())[:25]
    caption = next((b for b in blocks if b["page"] == page_no and " ".join(b["text"].split()).startswith(prefix)), None)
    if caption is None:
        return ["caption block not found in text.jsonl"]
    box = (caption["x0"], caption["y0"], caption["x1"], caption["y1"])
    captions = [b for b in blocks if b["page"] == page_no and frontend.CAPTION_ANY.match(b["text"])]
    rules = frontend.rule_groups(frontend.collect_rule_pieces(page))
    layout, reason = frontend.locate_table(box, rules, frontend.next_caption_below(caption, captions))
    if layout is None:
        return [f"layout not found: {reason}"]
    out = [f"layout: top {layout.top_y:.1f}, header bottom {layout.header_bottom_y:.1f}, closing {layout.closing_y:.1f}, "
           f"{len(layout.columns)} columns, x {layout.columns[0][0]:.1f}..{layout.columns[-1][1]:.1f}"]

    words = [{"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "text": w[4]} for w in page.get_text("words")]
    boxes = [(r["box_id"], (float(r["x0"]), float(r["y0"]), float(r["x1"]), float(r["y1"])))
             for r in regions if int(r["page"]) == page_no and r["gate"] in ("molecule", "uncertain")]
    left, right = layout.columns[0][0] - 5, layout.columns[-1][1] + 5
    zone, outside_x = [], 0
    for w in words:
        xc, yc = (w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2
        if layout.top_y <= yc <= layout.closing_y:
            if left <= xc <= right:
                zone.append(w)
            else:
                outside_x += 1
    swallowed: dict[str, list[dict]] = {}
    usable = []
    for w in zone:
        hit = next((bid for bid, b in boxes if frontend.overlap_fraction((w["x0"], w["y0"], w["x1"], w["y1"]), b) >= 0.5), None)
        if hit:
            swallowed.setdefault(hit, []).append(w)
        else:
            usable.append(w)
    out.append(f"words on the page: {len(words)} | at the table's height but outside its columns: {outside_x} | "
               f"in the table's area: {len(zone)} | swallowed by molecule boxes: {sum(len(v) for v in swallowed.values())} | "
               f"usable: {len(usable)}")
    lookup = dict(boxes)
    for bid, ws in sorted(swallowed.items(), key=lambda kv: -len(kv[1]))[:6]:
        b = lookup[bid]
        out.append(f"  box {bid} ({b[0]:.0f},{b[1]:.0f})-({b[2]:.0f},{b[3]:.0f}) swallowed {len(ws)} words, e.g. {[w['text'] for w in ws[:6]]}")
    header = [w for w in usable if (w["y0"] + w["y1"]) / 2 < layout.header_bottom_y]
    out.append(f"usable header words: {len(header)} | usable body words: {len(usable) - len(header)}")
    first = sorted(usable, key=lambda w: (w["y0"], w["x0"]))[:12]
    out.append("first usable words: " + (", ".join(f"{w['text']}@({w['x0']:.0f},{w['y0']:.0f})" for w in first) or "none"))
    # What is inside the table's area if not text? Images, vector shapes (outlined text, coloured cells), drawings.
    area = (layout.columns[0][0], layout.top_y, layout.columns[-1][1], layout.closing_y)
    inside = [bid for bid, b in boxes if frontend.overlap_fraction(b, area) >= 0.5]
    out.append(f"detected molecule boxes inside the table's area: {len(inside)} {inside[:8]}")
    infos = page.get_image_info() if hasattr(page, "get_image_info") else []
    images = [i["bbox"] for i in infos if frontend.overlap_fraction(tuple(i["bbox"]), area) >= 0.3]
    out.append(f"embedded images overlapping the area: {len(images)} "
               f"{[tuple(round(v) for v in b) for b in images[:4]]}")
    shapes = [d for d in page.get_drawings() if d.get("rect") is not None
              and frontend.overlap_fraction(rect_tuple(d["rect"]), area) >= 0.9]
    filled = sum(1 for d in shapes if d.get("fill") is not None)
    out.append(f"vector shapes inside the area: {len(shapes)} ({filled} filled, {len(shapes) - filled} stroked)")
    if not zone:
        out.append("NO extractable text inside the table's area: its contents are an image, outlined text, or drawings")
    return out


def main(argv: list[str]) -> int:
    if len(argv) not in (4, 5):
        print(__doc__)
        return 2
    import pymupdf  # imported here so describe() can be tested without it

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, so `pipeline` imports from here
    from pipeline import frontend

    run, paper, page_no = Path(argv[1]), argv[2], int(argv[3])
    which = int(argv[4]) if len(argv) == 5 else 1
    base = run / "papers" / paper
    tables = [t for t in read_jsonl(base / "tables.jsonl") if t["page"] == page_no]
    if len(tables) < which:
        print(f"paper {paper} page {page_no}: {len(tables)} table(s) found")
        return 1
    with (base / "regions.csv").open(newline="", encoding="utf-8") as stream:
        regions = list(csv.DictReader(stream))
    pdf = Path("data/internal") / f"{paper}.pdf"
    with pymupdf.open(pdf) as doc:
        print(f"{tables[which - 1]['table_id']}  status={tables[which - 1]['status']}  {tables[which - 1]['reason'] or ''}")
        print("\n".join(describe(frontend, doc[page_no - 1], page_no, tables[which - 1], read_jsonl(base / "text.jsonl"), regions)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
