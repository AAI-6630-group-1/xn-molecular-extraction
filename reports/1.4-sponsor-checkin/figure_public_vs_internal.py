#!/usr/bin/env python3
"""Figure for the 1.4 check-in: public-benchmark scores beside the share of molecules found in
our six papers, one row per system.

    uv run python benchmarks/score.py --all && uv run python benchmarks/aggregate.py
    uv run python reports/1.4-sponsor-checkin/figure_public_vs_internal.py

Reads benchmarks/results/comparison.csv (written by aggregate.py) and writes
public_vs_internal.png beside this script. Colors are the first three slots of the dataviz
reference palette, validated all-pairs for a dot plot; each series also has its own marker
shape and visible value labels, so color isn't the only cue.
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SERIES = [  # (comparison.csv column, legend label, color, marker, value label above or below the mark)
    ("BioVista test, all crops (accuracy)", "Public: BioVista journal-figure crops, read correctly", "#2a78d6", "o", "above"),
    ("Patent300 pages (F1)", "Public: Patent300 patent pages, F1", "#eb6834", "s", "below"),
    ("Internal papers (pooled recall)", "Our six papers: molecules found (of 220)", "#1baf7a", "D", "above"),
]
SHORT_NAMES = {  # comparison.csv system -> row label
    "MolDetV2 + MolScribe (patched)": "MolScribe\n(sponsor paper's reader)",
    "MolDetV2 + MolGlyph": "MolGlyph\n(BioMiner's reader)",
    "BioMiner, full (MinerU + MolDetV2 + MolGlyph + BioMiner-Instruct)": "Full BioMiner\n(+ layout and language model)",
}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def main() -> None:
    with open(REPO / "benchmarks/results/comparison.csv", newline="") as f:
        systems = [r for r in csv.DictReader(f) if r["system"] in SHORT_NAMES]

    fig, ax = plt.subplots(figsize=(7.2, 3.7), dpi=200)
    rows = list(range(len(systems)))[::-1]  # first system on top
    for y, system in zip(rows, systems):
        values = [float(system[col]) * 100 for col, *_ in SERIES if system[col]]
        ax.plot([min(values), max(values)], [y, y], color=MUTED, lw=1.2, alpha=0.5, zorder=1)  # the gap
        for col, label, color, marker, where in SERIES:
            if not system[col]:
                continue
            x = float(system[col]) * 100
            ax.plot(x, y, marker=marker, ms=8, color=color, mec="#fcfcfb", mew=1.5, ls="none", zorder=3)
            above = where == "above"
            ax.annotate(f"{x:.0f}%", (x, y), xytext=(0, 8 if above else -8), textcoords="offset points", ha="center",
                        va="bottom" if above else "top", fontsize=7.5, color=INK)
        if not system[SERIES[0][0]]:
            ax.annotate("public scores: same reader as MolGlyph", (float(system[SERIES[2][0]]) * 100, y), xytext=(14, 0),
                        textcoords="offset points", va="center", fontsize=7.5, color=MUTED)

    ax.set_yticks(rows, [SHORT_NAMES[s["system"]] for s in systems], fontsize=8, color=INK)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.55, len(systems) - 0.35)
    ax.set_xticks(range(0, 101, 20), [f"{v}%" for v in range(0, 101, 20)], fontsize=8, color=MUTED)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0)
    handles = [plt.Line2D([], [], marker=m, ms=7, color=c, ls="none") for _, _, c, m, _ in SERIES]
    ax.legend(handles, [label for _, label, *_ in SERIES], loc="upper center", bbox_to_anchor=(0.42, -0.10), ncol=1,
              frameon=False, fontsize=7.5, labelcolor=INK, handletextpad=0.4)
    fig.suptitle("Clean benchmarks overstate how well tools read real papers", x=0.02, ha="left", fontsize=10.5,
                 fontweight="bold", color=INK)
    fig.text(0.02, 0.905, "Public scores come from single molecules or patent pages; ours from six full journal PDFs (220 molecules).",
             fontsize=7.5, color=MUTED)
    fig.subplots_adjust(left=0.27, right=0.97, top=0.85, bottom=0.27)
    out = HERE / "public_vs_internal.png"
    fig.savefig(out, facecolor="#fcfcfb")
    print(f"wrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
