#!/usr/bin/env python3
"""Figures for the 1.3 individual benchmark report (willdaly, Track 3).

    uv run python reports/willdaly/figures_1_3.py

Figure 1: four example crops from paper 19 (CC BY 4.0) with each reader's
output. Crops come from data/track3_runs/, so run run_track3.py first.
Figure 2: what each MolDetV2 box on the six internal papers became, for each
reader, using analyze_track3.py's categories. Run score.py on both runs first.

Writes PNGs to reports/willdaly/figures/.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RESULTS = REPO / "benchmarks" / "results" / "willdaly"
OUT = HERE / "figures"
sys.path.insert(0, str(REPO / "benchmarks" / "willdaly"))
from analyze_track3 import classify_box, read  # noqa: E402

PAPERS = ["1", "2", "4", "6", "16", "19"]
# analyze_track3 categories, merged to five and drawn in this order (dataviz reference palette, slots 1-5).
CATEGORIES = [
    ("correct", "Correct molecule", "#2a78d6"),
    ("rgroup", "Markush piece: scaffold or substituent with *", "#eb6834"),
    ("multi_fragment", "Extra fragments (label text)", "#1baf7a"),
    ("invalid", "Invalid or empty", "#eda100"),
    ("wrong", "Other wrong molecule", "#e87ba4"),
]
TEXT, MUTED = "#0b0b0b", "#52514e"

plt.rcParams.update({"font.family": "Arial", "font.size": 7.5, "axes.edgecolor": MUTED,
                     "axes.labelcolor": TEXT, "xtick.color": MUTED, "ytick.color": TEXT})


def box_outcomes(run_dir: Path) -> tuple[dict[str, Counter], dict[str, int]]:
    """Count analyze_track3 categories per paper, and the number of ground-truth molecules per paper."""
    matches = read(run_dir / "matches.csv")
    truth = defaultdict(set)
    for m in matches:
        if m["side"] == "gt":
            truth[m["paper_id"]].add(m["smiles"])
    counts = {p: Counter() for p in PAPERS}
    for row in read(run_dir / "predictions.csv"):
        category = classify_box(row["smiles"], truth[row["paper_id"]])
        counts[row["paper_id"]]["invalid" if category == "no_output" else category] += 1
    return counts, {p: len(truth[p]) for p in PAPERS}


def figure_outcomes(runs: dict[str, Path], path: Path) -> None:
    data = {name: box_outcomes(run) for name, run in runs.items()}
    n_gt = next(iter(data.values()))[1]
    rows = [(p, name) for p in PAPERS for name in runs]  # two bars per paper
    fig, ax = plt.subplots(figsize=(6.5, 2.85), dpi=300)
    y_positions, labels = [], []
    y = 0.0
    for i, (paper, name) in enumerate(rows):
        if i and rows[i - 1][0] != paper:
            y += 0.4  # gap between papers
        y_positions.append(y)
        labels.append(f"Paper {paper} ({n_gt[paper]} mol.)  {name}" if name == list(runs)[0] else name)
        left = 0
        counts = data[name][0][paper]
        for key, _, color in CATEGORIES:
            n = counts[key]
            if n:
                ax.barh(y, n, left=left, height=0.82, color=color, edgecolor="white", linewidth=0.8)
                if n >= 3:
                    ax.text(left + n / 2, y, str(n), ha="center", va="center", fontsize=6, color=TEXT)
                left += n
        ax.text(left + 0.8, y, f"{left} boxes", ha="left", va="center", fontsize=6, color=MUTED)
        y += 1.0
    ax.set_yticks(y_positions, labels, fontsize=6.5)
    ax.invert_yaxis()
    ax.set_xlabel("MolDetV2 boxes on the page (each box's SMILES is one prediction)", fontsize=6.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True, color="#e4e3df", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(sum(c.values()) for d in data.values() for c in d[0].values()) * 1.12)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in CATEGORIES]
    ax.legend(handles, [label for _, label, _ in CATEGORIES], ncol=3, frameon=False, fontsize=6.3,
              loc="lower left", bbox_to_anchor=(-0.02, 1.0), handlelength=1.2, columnspacing=1.2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, facecolor="white")
    plt.close(fig)
    print(f"wrote {path.relative_to(REPO)}")


# Paper 19 (CC BY 4.0) boxes, with what each reader returned (from the two runs' predictions.csv).
EXAMPLES = [
    ("19-p12-10", "(a) Scheme compound", "Both readers: correct"),
    ("19-p9-5", "(b) R-group table cell", "MolScribe: CC.Cc1ccc(F)cc1C\nMolGlyph: *c1ccc(F)cc1C"),
    ("19-p6-0", "(c) Scaffold with R", "Both: the scaffold with *;\nits R-groups are in a table"),
    ("19-p1-0", "(d) 3D render", "MolScribe: invalid (conf. 0.00)\nMolGlyph: invented (conf. 0.81)"),
]


def figure_examples(crop_dir: Path, path: Path) -> None:
    """Four crops in equal-width slots, each with a title above and the readers' outputs below."""
    from PIL import Image
    fig_w, fig_h = 6.5, 1.75
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=300)
    gap = 0.02
    slot = (1 - gap * (len(EXAMPLES) - 1)) / len(EXAMPLES)
    img_bottom, img_h = 0.30, 0.58
    for i, (box, title, outcome) in enumerate(EXAMPLES):
        im = Image.open(crop_dir / f"{box}.png").convert("RGB")
        left = i * (slot + gap)
        # Fit the crop inside the slot at its own aspect ratio.
        w = min(slot, img_h * fig_h * im.width / im.height / fig_w)
        h = w * fig_w * im.height / im.width / fig_h
        ax = fig.add_axes((left, img_bottom + (img_h - h) / 2, w, h))
        ax.imshow(im)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#c3c2b7")
            spine.set_linewidth(0.6)
        fig.text(left, 0.93, title, fontsize=7, color=TEXT, ha="left", va="bottom", fontweight="bold")
        fig.text(left, 0.25, outcome, fontsize=6.3, color=TEXT, ha="left", va="top")
    fig.savefig(path, dpi=300, facecolor="white", bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    print(f"wrote {path.relative_to(REPO)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--molscribe", default="2026-10-04_moldetv2-molscribe-pad0_internal")
    # Each reader with the crop margin Patent300 chose for it: 0 px for MolScribe, 10 px for MolGlyph.
    ap.add_argument("--molglyph", default="2026-10-06_moldetv2-molglyph_internal")
    args = ap.parse_args()
    runs = {"MolScribe": RESULTS / args.molscribe, "MolGlyph": RESULTS / args.molglyph}
    for name, run in runs.items():
        if not (run / "matches.csv").exists():
            sys.exit(f"{run} has no matches.csv; run score.py on it first")
    figure_examples(REPO / "data" / "track3_runs" / args.molscribe, OUT / "fig1_examples.png")
    figure_outcomes(runs, OUT / "fig2_box_outcomes.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
