#!/usr/bin/env python3
"""Track 3 smoke test: PDF pages -> MolDetV2 boxes -> MolScribe SMILES -> ground truth.

Renders every page of one internal paper with PyMuPDF, detects molecule drawings
with MolDetV2 (the 960 px "doc" YOLO11n weights), crops each box, reads it with
MolScribe, and compares the canonical SMILES (RDKit, canonicalized exactly as
benchmarks/score.py does) against the paper's ground truth. Separately times
Docling's picture export on the same PDF and counts the pictures it finds.

    .venv-track3/bin/python benchmarks/willdaly/smoke_test_track3.py --paper 16
    .venv-track3/bin/python benchmarks/willdaly/smoke_test_track3.py --paper 16 --device cpu

Outputs (crops, detections.csv, summary.json) go to data/smoke_track3/paper<id>/,
which is gitignored because the crops come from the papers.
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pymupdf
import torch
from huggingface_hub import hf_hub_download
from PIL import Image
from rdkit import Chem, DataStructs, rdBase

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "benchmarks"))
from score import GROUND_TRUTH, load_ground_truth, parse  # noqa: E402  same canonicalization as the scorer

warnings.filterwarnings("ignore")  # timm/onmt/albumentations emit deprecation noise under torch 2.x


def patch_molscribe() -> None:
    """Fix MolScribe's abbreviation expansion (Ph, OMe, Boc, ...) on this platform.

    molscribe.chemistry._expand_functional_group reads each bond's order *after*
    RWMol.RemoveBond has deleted it. The stale Bond object reports order 0 here
    (macOS arm64, RDKit 2022.09 through 2026.03), so BOND_TYPES[0] raises KeyError
    and every molecule with an abbreviation comes back '<invalid>'. The fix reads
    the orders before removing the bonds.
    """
    import molscribe.chemistry as chem

    src = inspect.getsource(chem._expand_functional_group)
    old_1 = "adjacent_indices = [bond.GetOtherAtomIdx(i) for bond in bonds]"
    old_2 = ("for adjacent_atom, bond in zip(adjacent_atoms, bonds):\n"
             "                    adjacent_atom.SetNumRadicalElectrons(int(bond.GetBondTypeAsDouble()))")
    assert old_1 in src and old_2 in src, "MolScribe source changed; re-check the patch"
    src = src.replace(old_1, old_1 + "\n                bond_orders = [int(b.GetBondTypeAsDouble()) for b in bonds]")
    src = src.replace(old_2, "for adjacent_atom, order in zip(adjacent_atoms, bond_orders):\n"
                             "                    adjacent_atom.SetNumRadicalElectrons(order)")
    exec(src, chem.__dict__)  # redefines _expand_functional_group inside molscribe.chemistry


def largest_fragment(mol):
    """Drop stray fragments (label text, stray H/N atoms) and keep the biggest piece."""
    frags = Chem.GetMolFrags(Chem.MolFromSmiles(mol.smiles), asMols=True)
    return parse(Chem.MolToSmiles(max(frags, key=lambda m: m.GetNumHeavyAtoms())))


def render(pdf: Path, dpi: int) -> list[np.ndarray]:
    """Render each page to an RGB uint8 array."""
    pages = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            pages.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).copy())
    return pages


def docling_pictures(pdf: Path, out: Path) -> tuple[int, float]:
    """Convert with Docling (layout only: no OCR, no table model) and save every picture."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=False,
                              generate_picture_images=True, images_scale=2.0)
    t0 = time.perf_counter()
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    doc = converter.convert(pdf).document
    out.mkdir(parents=True, exist_ok=True)
    for n, pic in enumerate(doc.pictures):
        img = pic.get_image(doc)
        if img is not None:
            img.save(out / f"docling_p{pic.prov[0].page_no}_{n}.png")
    return len(doc.pictures), time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paper", default="16")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--conf", type=float, default=0.5, help="MolDetV2 confidence threshold (model card uses 0.5)")
    ap.add_argument("--pad", type=int, default=10, help="pixels added around each box before MolScribe")
    ap.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    ap.add_argument("--skip-docling", action="store_true")
    args = ap.parse_args()

    pdf = REPO / "data" / "internal" / f"{args.paper}.pdf"
    out = REPO / "data" / "smoke_track3" / f"paper{args.paper}_{args.device}"
    (out / "crops").mkdir(parents=True, exist_ok=True)
    t_total, times = time.perf_counter(), {}

    t0 = time.perf_counter()
    det_w = hf_hub_download("UniParser/MolDetv2", "moldet_v2_yolo11n_960_doc.pt")
    ocsr_w = hf_hub_download("yujieq/MolScribe", "swin_base_char_aux_1m.pth")
    times["weights_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    pages = render(pdf, args.dpi)
    times["render_s"] = time.perf_counter() - t0

    from ultralytics import YOLO
    t0 = time.perf_counter()
    detector = YOLO(det_w)
    boxes = []  # (page_no, x0, y0, x1, y1 in pixels, conf)
    for page_no, img in enumerate(pages, start=1):
        # Ultralytics treats numpy input as BGR, so flip the channels.
        result = detector.predict(img[..., ::-1], imgsz=960, conf=args.conf, device=args.device, verbose=False)[0]
        for xyxy, conf in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()):
            boxes.append((page_no, *xyxy, conf))
    times["detect_s"] = time.perf_counter() - t0

    crops = []
    for n, (page_no, x0, y0, x1, y1, _) in enumerate(boxes):
        h, w, _ = pages[page_no - 1].shape
        x0, y0 = max(0, int(x0) - args.pad), max(0, int(y0) - args.pad)
        x1, y1 = min(w, int(x1) + args.pad), min(h, int(y1) + args.pad)
        crop = pages[page_no - 1][y0:y1, x0:x1]
        crops.append(crop)
        Image.fromarray(crop).save(out / "crops" / f"p{page_no}_{n}.png")

    from molscribe import MolScribe
    patch_molscribe()
    t0 = time.perf_counter()
    reader = MolScribe(ocsr_w, device=torch.device(args.device))
    times["ocsr_load_s"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    preds = reader.predict_images(crops, return_confidence=True, batch_size=8) if crops else []
    times["ocsr_s"] = time.perf_counter() - t0

    truth = load_ground_truth(GROUND_TRUTH["internal"])[str(int(args.paper))]
    rows, predicted = [], []
    for (page_no, x0, y0, x1, y1, conf), pred in zip(boxes, preds):
        mol = parse(pred["smiles"])
        predicted.append(mol)
        scale = 72 / args.dpi  # pixels -> PDF points
        rows.append({"paper_id": args.paper, "page": page_no,
                     "x0": round(x0 * scale, 1), "y0": round(y0 * scale, 1),
                     "x1": round(x1 * scale, 1), "y1": round(y1 * scale, 1),
                     "det_conf": round(conf, 3), "smiles": pred["smiles"],
                     "ocsr_conf": round(float(pred["confidence"]), 3), "valid": mol.valid,
                     "canonical": mol.smiles if mol.valid else ""})
    with open(out / "detections.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["paper_id"])
        writer.writeheader()
        writer.writerows(rows)

    valid = [p for p in predicted if p.valid]
    keys, blind = {p.key for p in valid}, {p.stereo_blind for p in valid}
    main = [largest_fragment(p) for p in valid]  # secondary metric, not what score.py does
    main_keys, main_blind = {p.key for p in main}, {p.stereo_blind for p in main}
    per_gt = []
    for g in truth.values():
        sims = DataStructs.BulkTanimotoSimilarity(g.fingerprint, [p.fingerprint for p in valid]) if valid else []
        best = int(np.argmax(sims)) if sims else None
        per_gt.append({"name": "/".join(g.names), "exact": g.key in keys, "stereo_blind": g.stereo_blind in blind,
                       "exact_largest_frag": g.key in main_keys, "blind_largest_frag": g.stereo_blind in main_blind,
                       "best_tanimoto": round(sims[best], 3) if sims else 0.0,
                       "nearest_pred": valid[best].smiles if sims else None, "gt": g.smiles})

    if not args.skip_docling:
        n_pics, times["docling_s"] = docling_pictures(pdf, out / "docling")
    times["total_s"] = time.perf_counter() - t_total

    summary = {
        "paper": args.paper, "device": args.device, "dpi": args.dpi, "conf": args.conf,
        "pages": len(pages), "boxes": len(boxes), "smiles_valid": len(valid),
        "unique_valid": len(keys), "n_gt": len(truth),
        "exact_matches": sum(r["exact"] for r in per_gt),
        "stereo_blind_matches": sum(r["stereo_blind"] for r in per_gt),
        "exact_matches_largest_fragment": sum(r["exact_largest_frag"] for r in per_gt),
        "stereo_blind_matches_largest_fragment": sum(r["blind_largest_frag"] for r in per_gt),
        "docling_pictures": None if args.skip_docling else n_pics,
        "rdkit": rdBase.rdkitVersion, "torch": torch.__version__,
        "times_s": {k: round(v, 2) for k, v in times.items()}, "per_gt": per_gt,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_gt"}, indent=2))
    for r in per_gt:
        print(f"  {r['name']:>6}  exact={r['exact']!s:5}  blind={r['stereo_blind']!s:5}  "
              f"largest-frag exact={r['exact_largest_frag']!s:5} blind={r['blind_largest_frag']!s:5}  "
              f"best_tanimoto={r['best_tanimoto']}")
    print(f"outputs in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
