#!/usr/bin/env python3
"""Fetch the public datasets Track 3 benchmarks on, and check the internal one is in place.

    uv run python benchmarks/willdaly/download_data.py              # everything
    uv run python benchmarks/willdaly/download_data.py --biovista   # one dataset

- MolMole Patent300 (151 MB, CC BY-NC-ND 4.0) from Hugging Face into
  data/patent300/: 300 patent pages with a box and a molfile per molecule.
- BioVista OCSR (61 MB) from the Google Drive link in BioMiner's README into
  data/biovista/: 8,861 molecule crops with SMILES, plus BioVista's
  test/validation split lists from the BioMiner repository.
- The internal papers come from Canvas (Dataset 2.zip in the XN Project
  module), which needs a course login, so this script only checks they're in
  data/internal/ and says what to do if not.

Everything lands in data/, which git ignores. Already-downloaded datasets are
skipped, so rerunning is safe.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
from molglyph import BIOMINER_COMMIT  # noqa: E402  the BioVista split lists come from the same commit

BIOVISTA_OCSR = "https://drive.usercontent.google.com/download?id=11iCH0j7U9iFgwXahjkWZouNyqATfEPoL&export=download&confirm=t"
BIOVISTA_SPLITS = f"https://raw.githubusercontent.com/jiaxianyan/BioMiner/{BIOMINER_COMMIT}/BioVista/{{}}"
INTERNAL_FILES = ["1.pdf", "2.pdf", "4.pdf", "6.pdf", "16.pdf", "19.pdf",
                  "ground_truth_SMILES_confirmed_1,2,4,6,16,19.csv"]


def fetch(url: str, dest: Path) -> None:
    """Stream a URL to a file, writing to a temporary name first so an interrupted download isn't mistaken for a finished one."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, open(tmp, "wb") as f:
        shutil.copyfileobj(response, f)
    tmp.rename(dest)


def patent300() -> None:
    root = DATA / "patent300"
    if len(list((root / "images_300").glob("*.png"))) == 300:
        print("patent300: already in data/patent300/")
        return
    from huggingface_hub import snapshot_download
    print("patent300: downloading 151 MB from Hugging Face ...", flush=True)
    snapshot_download("doxa-friend/MolMole_Patent300", repo_type="dataset", local_dir=root)
    n = len(list((root / "images_300").glob("*.png")))
    print(f"patent300: {n} page images in data/patent300/")


def biovista() -> None:
    root = DATA / "biovista"
    root.mkdir(parents=True, exist_ok=True)
    crops = root / "ocsr" / "data"
    if len(list(crops.glob("*.png"))) != 8861:
        archive = root / "ocsr.tar.gz"
        if not archive.exists():
            print("biovista: downloading the OCSR set (61 MB) from Google Drive ...", flush=True)
            fetch(BIOVISTA_OCSR, archive)
        if not tarfile.is_tarfile(archive):
            archive.unlink()
            sys.exit("biovista: Google Drive returned a web page instead of the archive; download "
                     "ocsr.tar.gz by hand from the OCSR link in BioMiner's README into data/biovista/")
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
    for name in ("test_set_names.txt", "valid_set_names.txt"):
        if not (root / name).exists():
            fetch(BIOVISTA_SPLITS.format(name), root / name)
    n = len(list(crops.glob("*.png")))
    print(f"biovista: {n} crops and labels in data/biovista/ocsr/, split lists in data/biovista/")


def internal() -> bool:
    missing = [name for name in INTERNAL_FILES if not (DATA / "internal" / name).exists()]
    if missing:
        print("internal: missing " + ", ".join(missing) + ". Download 'Dataset 2.zip' from the Canvas XN Project "
              "module and unzip it into data/internal/ (see data/README.md).")
        return False
    print("internal: all six papers and the ground truth are in data/internal/")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patent300", action="store_true")
    ap.add_argument("--biovista", action="store_true")
    ap.add_argument("--internal", action="store_true", help="only check that the internal papers are in place")
    args = ap.parse_args()
    everything = not (args.patent300 or args.biovista or args.internal)
    if everything or args.patent300:
        patent300()
    if everything or args.biovista:
        biovista()
    ok = internal() if everything or args.internal else True
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
