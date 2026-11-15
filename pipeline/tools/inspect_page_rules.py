"""Print the horizontal rules, rectangles and caption blocks of one page, to design caption-anchored table clipping.

Usage (from the repo root):
    uv run python pipeline/tools/inspect_page_rules.py <paper_id> <page_number>
    uv run python pipeline/tools/inspect_page_rules.py 2 8
    uv run python pipeline/tools/inspect_page_rules.py 19 5

Looks at the individual segments and rectangles inside each drawing path (a table's header lines are often several
segments in one path, so the path's own bounding box hides them). Reads data/internal/<paper_id>.pdf and writes
nothing. Coordinates are PDF points, unrotated, top-left origin.
AI disclosure: Claude (Anthropic) drafted this helper for Peter Adranly; it was tested with fake page objects first,
then run by Peter on pages of the six course papers.
"""
import re
import sys
from pathlib import Path

CAPTION = re.compile(r"^\s*(Table|Figure|Scheme|Chart)\s+\d+")
MAX_LINES = 50


def collect(page):
    """Return (horizontal pieces, rectangles) found among the segments and rectangles of every drawing path."""
    pieces, boxes = [], []          # pieces: (y, x0, x1, thickness)   boxes: (y0, y1, x0, x1, filled)
    for drawing in page.get_drawings():
        filled = drawing.get("fill") is not None
        stroke = drawing.get("width") or 0
        for item in drawing["items"]:
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) <= 0.5 and abs(p2.x - p1.x) >= 15:
                    pieces.append(((p1.y + p2.y) / 2, min(p1.x, p2.x), max(p1.x, p2.x), stroke))
            elif kind in ("re", "qu"):
                rect = item[1] if kind == "re" else item[1].rect
                if rect.height <= 2.5 and rect.width >= 15:
                    pieces.append((rect.y0, rect.x0, rect.x1, rect.height))
                elif 8 <= rect.height <= 60 and rect.width >= 30:
                    boxes.append((rect.y0, rect.y1, rect.x0, rect.x1, filled))
    return pieces, boxes


def describe(page) -> str:
    out = [f"page rect {tuple(round(v) for v in page.rect)}  rotation {page.rotation}"]
    pieces, boxes = collect(page)

    by_y = {}
    for y, x0, x1, thick in pieces:
        by_y.setdefault(round(y * 2) / 2, []).append((x0, x1, thick))
    out.append(f"\n{len(by_y)} heights with horizontal rule pieces (y, pieces, total width, x range, thickness):")
    for y in sorted(by_y)[:MAX_LINES]:
        parts = by_y[y]
        out.append(f"  y={y:7.1f}   {len(parts):>2} pieces   total {sum(b - a for a, b, _ in parts):6.1f}   "
                   f"x {min(a for a, _, _ in parts):6.1f}..{max(b for _, b, _ in parts):6.1f}   "
                   f"thick {max(t for _, _, t in parts):4.2f}")

    grouped = {}
    for y0, y1, x0, x1, filled in boxes:
        grouped.setdefault((round(y0), round(y1), filled), []).append((x0, x1))
    out.append(f"\n{len(grouped)} kinds of rectangles 8-60 pt tall and 30+ wide (y0..y1, count, x range, filled?):")
    for (y0, y1, filled), parts in sorted(grouped.items())[:MAX_LINES]:
        out.append(f"  y={y0:5d}..{y1:5d}   {len(parts):>2} rects   x {min(a for a, _ in parts):6.1f}..{max(b for _, b in parts):6.1f}"
                   f"   {'filled' if filled else 'stroked'}")

    out.append("\ncaption-like text blocks (y range, x range, start of text):")
    for x0, y0, x1, y1, text, _number, kind in sorted(page.get_text("blocks"), key=lambda b: (b[1], b[0])):
        if kind == 0 and CAPTION.match(text):
            out.append(f"  y={y0:7.1f}..{y1:7.1f}   x {x0:6.1f}..{x1:6.1f}   {text[:48].strip()!r}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    import pymupdf  # imported here so describe() can be tested without it

    pdf = Path("data/internal") / f"{argv[1]}.pdf"
    if not pdf.is_file():
        print(f"{pdf} not found; run this from the repo root")
        return 1
    with pymupdf.open(pdf) as doc:
        page_no = int(argv[2])
        if not 1 <= page_no <= len(doc):
            print(f"{pdf.name} has {len(doc)} pages")
            return 1
        print(f"paper {argv[1]}, page {page_no}")
        print(describe(doc[page_no - 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
