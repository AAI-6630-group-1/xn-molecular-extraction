#!/usr/bin/env python3
"""Precision and recall at IoU 0.5 on MolDet-Bench-Doc, split journal vs patent and by box size.

Run bench_eval.py first. The dataset doesn't mark which pages are journal pages,
so JOURNAL was picked by eye from page thumbnails; treat the split as approximate.
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
E = REPO / "benchmarks" / "results" / "willdaly" / "2026-11-06_moldetv2_moldet-bench-doc"
D = REPO / "data" / "moldet_bench" / "MolDet-Bench-Doc"
# Judged by eye from thumbnails; pages not listed were read as patents.
JOURNAL = {f"doc_{n:03d}" for n in
           (17, 71, 89, 92, 122, 129, 171, 174, 197, 215, 236, 259, 291, 303, 388, 396, 397, 402, 437)}
pred = pd.read_csv(E / "pred.csv")
sizes = pd.read_csv(E / "pages.csv").set_index("page")


def gt_boxes(page: str) -> np.ndarray:
    W, H = sizes.loc[page, ["W", "H"]]
    rows = []
    for line in (D / "labels" / f"{page}.txt").read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        _, xc, yc, w, h = map(float, parts[:5])
        rows.append(((xc - w / 2) * W, (yc - h / 2) * H, (xc + w / 2) * W, (yc + h / 2) * H))
    return np.array(rows).reshape(-1, 4)


def iou(a: np.ndarray, B: np.ndarray) -> np.ndarray:
    ix = np.clip(np.minimum(a[2], B[:, 2]) - np.maximum(a[0], B[:, 0]), 0, None)
    iy = np.clip(np.minimum(a[3], B[:, 3]) - np.maximum(a[1], B[:, 1]), 0, None)
    i = ix * iy
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (B[:, 2] - B[:, 0]) * (B[:, 3] - B[:, 1]) - i + 1e-9)


def match(page: str, sz: int, conf: float) -> tuple[np.ndarray, int, int]:
    """Greedy one-to-one matching by confidence. Returns per-GT hit flags, TP, and box count."""
    G = gt_boxes(page)
    p = pred[(pred.imgsz == sz) & (pred.page == page) & (pred.conf >= conf)].sort_values("conf", ascending=False)
    used = np.zeros(len(G), bool)
    tp = 0
    for row in p.itertuples():
        if not len(G):
            break
        v = iou(np.array([row.x0, row.y0, row.x1, row.y1]), G)
        v[used] = 0
        j = int(v.argmax())
        if v[j] >= 0.5:
            used[j] = True
            tp += 1
    return used, tp, len(p)


pages = list(sizes.index)
rows, bins = [], []
for sz in (960, 1280, 1600):
    for conf in (0.5, 0.26):
        for name, sel in (("journal", [p for p in pages if p in JOURNAL]),
                          ("patent", [p for p in pages if p not in JOURNAL])):
            n_gt = tp = n_pred = 0
            for page in sel:
                used, t, n = match(page, sz, conf)
                G = gt_boxes(page)
                n_gt += len(G)
                tp += t
                n_pred += n
                W = sizes.loc[page, "W"]
                if len(G):
                    side = np.maximum(G[:, 2] - G[:, 0], G[:, 3] - G[:, 1]) / W
                    for s, h in zip(side, used):
                        bins.append((sz, conf, name, "<4%" if s < .04 else "4-10%" if s < .10 else ">=10%", bool(h)))
            rows.append((sz, conf, name, len(sel), n_gt, n_pred, tp, n_gt - tp, n_pred - tp,
                         round(tp / max(n_gt, 1), 4), round(tp / max(n_pred, 1), 4)))
print(pd.DataFrame(rows, columns="imgsz conf set pages gt pred tp missed extra recall precision".split())
      .to_string(index=False))
b = pd.DataFrame(bins, columns="imgsz conf set size hit".split())
t = b[b.conf == 0.5].groupby(["set", "size", "imgsz"]).hit.agg(["size", "sum"])
t["recall"] = (t["sum"] / t["size"]).round(3)
print(t.to_string())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion."""
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - m) / d, 3), round((c + m) / d, 3)


base = next(r for r in rows if r[:3] == (960, 0.5, "journal"))
print("journal recall 95% interval", wilson(base[6], base[4]), "precision", wilson(base[6], base[5]))
pd.DataFrame(rows, columns="imgsz conf set pages gt pred tp missed extra recall precision".split()).to_csv(
    E / "scores.csv", index=False)
