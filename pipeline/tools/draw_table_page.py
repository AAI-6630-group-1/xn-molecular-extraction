"""Draw a front-end run's table boxes and detected molecule boxes onto one page and save a PNG.

Usage (from the repo root):
    uv run python pipeline/tools/draw_table_page.py data/pipeline_runs/<run> 2 5        # paper 2, page 5

Red = table box, green = detected molecule boxes (numbered by their box id suffix), blue = a table's scaffold box.
Writes data/debug/<run>_paper<id>_p<page>.png; the PDF itself is not changed. The page images come from papers whose
licences forbid redistribution: keep data/debug out of git and out of public places.
AI disclosure: Claude (Anthropic) drafted this helper for Peter Adranly.
"""
import csv
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    import pymupdf

    run, paper, page_no = Path(argv[1]), argv[2], int(argv[3])
    base = run / "papers" / paper
    lines = [l for l in (base / "tables.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    tables = [t for t in map(json.loads, lines) if t["page"] == page_no]
    with (base / "regions.csv").open(newline="", encoding="utf-8") as stream:
        regions = [r for r in csv.DictReader(stream) if int(r["page"]) == page_no]
    scaffolds = {t["scaffold_box_id"] for t in tables if t["scaffold_box_id"]}
    with pymupdf.open(Path("data/internal") / f"{paper}.pdf") as doc:
        page = doc[page_no - 1]
        for t in tables:
            page.draw_rect(pymupdf.Rect(*t["bbox"]), color=(1, 0, 0), width=1.5)
        for r in regions:
            rect = pymupdf.Rect(float(r["x0"]), float(r["y0"]), float(r["x1"]), float(r["y1"]))
            colour = (0, 0, 1) if r["box_id"] in scaffolds else (0, 0.6, 0)
            page.draw_rect(rect, color=colour, width=0.8)
            page.insert_text((rect.x0 + 1, rect.y0 + 6), r["box_id"].rsplit("-", 1)[-1], fontsize=5, color=colour)
        out = Path("data/debug") / f"{run.name}_paper{paper}_p{page_no}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(dpi=110).save(out)
    print(f"wrote {out}: {len(tables)} table box(es), {len(regions)} molecule boxes on the page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
