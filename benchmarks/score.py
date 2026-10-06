#!/usr/bin/env python3
"""Score benchmark runs against the ground-truth SMILES.

Implements the scoring rules proposed on issue #14: exact match of canonical
SMILES under RDKit 2026.3.2, unique molecules per paper on both sides,
precision / recall / F1 per paper, and an equal-weight (macro) row and a
pooled row across papers.
https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/14#issuecomment-5841983072

    python benchmarks/score.py benchmarks/results/<handle>/<run_id>
    python benchmarks/score.py --all

A run folder holds run.json and predictions.csv (see benchmarks/README.md).
Scoring writes scores.csv and matches.csv into the run folder; --all scores
every run under benchmarks/results/ and stacks the scores into
benchmarks/results/summary.csv (e2e runs on the internal papers) and one
summary_<task>_<dataset>.csv per other task and dataset.

Runs on page-image datasets with ground-truth boxes (MolMole Patent300) are
scored by score_boxes.py, which handles detect, ocsr and e2e tasks.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path

from rdkit import Chem, DataStructs, RDLogger, rdBase
from rdkit.Chem import rdFingerprintGenerator

RDLogger.DisableLog("rdApp.*")  # invalid predictions are expected; don't flood the terminal

BENCHMARKS = Path(__file__).resolve().parent
REPO = BENCHMARKS.parent
RESULTS = BENCHMARKS / "results"
TAGS = BENCHMARKS / "gt_tags.csv"
GROUND_TRUTH = {
    "internal": REPO / "data" / "internal" / "ground_truth_SMILES_confirmed_1,2,4,6,16,19.csv",
}
# Page images with ground-truth boxes; runs on these are scored by score_boxes.py.
BOX_DATASETS = {
    "patent300": REPO / "data" / "patent300",
}
# The sponsor paper's version. Canonical SMILES can change between RDKit releases.
RDKIT_VERSION = "2026.03.2"
SOURCES = ("drawing", "name", "text", "unknown")

SCORE_COLUMNS = [
    "run_id", "handle", "tool", "dataset", "paper_id",
    "n_gt", "n_output_raw", "n_output", "n_invalid", "tp",
    "precision", "recall", "f1", "recall_stereo_blind",
    "n_gt_local", "recall_local_names", "mean_best_tanimoto", "rdkit_version",
]
MATCH_COLUMNS = [
    "paper_id", "side", "status", "valid", "smiles", "names", "n_rows", "pages", "sources",
    "stereo_blind_match", "best_tanimoto", "nearest_smiles", "nearest_names",
    "name_type", "challenge",
]

_morgan = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


class ScoringError(Exception):
    """A problem with a run's files that whoever made the run has to fix."""


@dataclass
class Molecule:
    """One unique molecule on either side of the match, with every row it came from."""

    key: str  # canonical SMILES, or "invalid:<raw>" for a prediction RDKit rejects
    smiles: str  # canonical SMILES, or the raw string if invalid
    stereo_blind: str | None = None
    fingerprint: object | None = None
    rows: int = 0
    names: list[str] = field(default_factory=list)  # ground-truth names, or labels the tool attached
    pages: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    name_type: str = ""  # "public", "local", or "" if untagged (ground truth only)
    challenge: str = ""

    @property
    def valid(self) -> bool:
        return self.fingerprint is not None


@dataclass
class PaperScore:
    """Counts for one paper. Summing the counts over papers gives the pooled score."""

    paper_id: str
    n_gt: int = 0
    n_output_raw: int = 0
    n_output: int = 0
    n_invalid: int = 0
    tp: int = 0
    tp_stereo_blind: int = 0
    n_gt_local: int = 0
    tp_local: int = 0
    sum_best_tanimoto: float = 0.0

    @classmethod
    def pooled(cls, scores: list[PaperScore]) -> PaperScore:
        counts = [f.name for f in fields(cls) if f.name != "paper_id"]
        return cls("pooled", **{name: sum(getattr(s, name) for s in scores) for name in counts})

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.n_output)  # 0 when the tool output nothing

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.n_gt)

    @property
    def f1(self) -> float:
        return _ratio(2 * self.precision * self.recall, self.precision + self.recall)

    @property
    def recall_stereo_blind(self) -> float:
        return _ratio(self.tp_stereo_blind, self.n_gt)

    @property
    def recall_local_names(self) -> float | None:
        return self.tp_local / self.n_gt_local if self.n_gt_local else None

    @property
    def mean_best_tanimoto(self) -> float:
        return _ratio(self.sum_best_tanimoto, self.n_gt)


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _add(values: list[str], value: str | None) -> None:
    value = (value or "").strip()
    if value and value not in values:
        values.append(value)


def parse(smiles: str) -> Molecule:
    """Canonicalize one SMILES string the way every run is scored.

    R-group placeholders lose their atom-map numbers and isotope labels, so
    `[*:1]`, `[1*]` and `*` compare equal.
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:  # treat anything RDKit rejects as invalid, whether it returns None or raises
        mol = None
    if mol is None:
        return Molecule(key="invalid:" + smiles, smiles=smiles)
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetAtomMapNum(0)
            atom.SetIsotope(0)
    canonical = Chem.MolToSmiles(mol)
    return Molecule(
        key=canonical,
        smiles=canonical,
        stereo_blind=Chem.MolToSmiles(mol, isomericSmiles=False),
        fingerprint=_morgan.GetFingerprint(mol),
    )


def paper_key(value: str) -> str:
    """Normalize a paper ID so '01' and '1' are the same paper."""
    value = (value or "").strip()
    return str(int(value)) if value.isdigit() else value


def _paper_order(paper: str) -> tuple:
    return (0, int(paper), "") if paper.isdigit() else (1, 0, paper)


def _column(fieldnames: list[str] | None, path: Path, *candidates: str) -> str:
    for name in candidates:
        if name in (fieldnames or []):
            return name
    raise ScoringError(f"{path} has no {' or '.join(repr(c) for c in candidates)} column")


def load_tags(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Read gt_tags.csv into {(paper_id, name): row}. A missing file means no tags."""
    if not path.exists():
        return {}
    tags = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            name_type = (row.get("name_type") or "").strip()
            if name_type not in ("", "public", "local"):
                raise ScoringError(f"{path}:{line}: name_type must be public, local, or blank, not {name_type!r}")
            tags[(paper_key(row["paper_id"]), row["name"].strip())] = {
                "name_type": name_type,
                "challenge": (row.get("challenge") or "").strip(),
            }
    return tags


def load_ground_truth(path: Path, tags: dict | None = None) -> dict[str, dict[str, Molecule]]:
    """Read the ground truth into unique molecules per paper, keyed by canonical SMILES.

    A molecule listed twice under different names (the #63 duplicates) becomes
    one molecule carrying both names. It counts as `public` if any of its names
    is tagged public, and as `local` only if all of them are tagged local.
    """
    tags = tags or {}
    papers: dict[str, dict[str, Molecule]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        paper_col = _column(reader.fieldnames, path, "paper_id", "paperID")
        name_col = _column(reader.fieldnames, path, "name", "name of molecule")
        smiles_col = _column(reader.fieldnames, path, "smiles", "canonical_SMILES")
        for line, row in enumerate(reader, start=2):
            paper, name = paper_key(row[paper_col]), row[name_col].strip()
            parsed = parse(row[smiles_col].strip())
            if not parsed.valid:
                raise ScoringError(f"{path}:{line}: RDKit can't parse the ground-truth SMILES for {name!r}")
            mol = papers.setdefault(paper, {}).setdefault(parsed.key, parsed)
            mol.rows += 1
            mol.names.append(name)

    for paper, molecules in papers.items():
        for mol in molecules.values():
            tagged = [tags.get((paper, name), {}) for name in mol.names]
            name_types = [t.get("name_type", "") for t in tagged]
            if "public" in name_types:
                mol.name_type = "public"
            elif all(t == "local" for t in name_types):
                mol.name_type = "local"
            challenges: list[str] = []
            for t in tagged:
                _add(challenges, t.get("challenge"))
            mol.challenge = "; ".join(challenges)
    return papers


def load_predictions(path: Path, known_papers) -> dict[str, dict[str, Molecule]]:
    """Read predictions.csv into unique predicted molecules per paper.

    Rows with an empty SMILES are skipped. An unknown paper_id or source is an
    error rather than a silent zero, since it usually means a typo.
    """
    if not path.exists():
        raise ScoringError(f"{path} is missing")
    predicted: dict[str, dict[str, Molecule]] = {}
    unknown_papers, unknown_sources = set(), set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"paper_id", "smiles"} - set(reader.fieldnames or [])
        if missing:
            raise ScoringError(f"{path} is missing the column(s) {', '.join(sorted(missing))}")
        for row in reader:
            smiles = (row["smiles"] or "").strip()
            if not smiles:
                continue
            paper = paper_key(row["paper_id"])
            source = (row.get("source") or "").strip() or "drawing"
            if paper not in known_papers:
                unknown_papers.add(paper)
                continue
            if source not in SOURCES:
                unknown_sources.add(source)
                continue
            parsed = parse(smiles)
            mol = predicted.setdefault(paper, {}).setdefault(parsed.key, parsed)
            mol.rows += 1
            _add(mol.names, row.get("label"))
            _add(mol.pages, row.get("page"))
            _add(mol.sources, source)
    if unknown_papers:
        raise ScoringError(f"{path}: paper_id(s) not in the ground truth: {', '.join(sorted(unknown_papers))}")
    if unknown_sources:
        raise ScoringError(f"{path}: source must be one of {', '.join(SOURCES)}, not {', '.join(sorted(unknown_sources))}")
    return predicted


def _nearest(mol: Molecule, others: list[Molecule]) -> tuple[Molecule | None, float]:
    """The most similar valid molecule on the other side, and its Tanimoto similarity."""
    candidates = [o for o in others if o.valid]
    if not mol.valid or not candidates:
        return None, 0.0
    sims = DataStructs.BulkTanimotoSimilarity(mol.fingerprint, [o.fingerprint for o in candidates])
    best = max(range(len(sims)), key=sims.__getitem__)
    return candidates[best], sims[best]


def _match_row(paper: str, side: str, status: str, mol: Molecule, nearest: Molecule | None,
               similarity: float, stereo_blind_match: bool) -> dict:
    return {
        "paper_id": paper,
        "side": side,
        "status": status,
        "valid": mol.valid,
        "smiles": mol.smiles,
        "names": "; ".join(mol.names),
        "n_rows": mol.rows,
        "pages": "; ".join(mol.pages),
        "sources": "; ".join(mol.sources),
        "stereo_blind_match": stereo_blind_match,
        "best_tanimoto": f"{similarity:.4f}" if nearest else "",
        "nearest_smiles": nearest.smiles if nearest else "",
        "nearest_names": "; ".join(nearest.names) if nearest else "",
        "name_type": mol.name_type,
        "challenge": mol.challenge,
    }


def score_paper(paper: str, truth: dict[str, Molecule],
                predicted: dict[str, Molecule]) -> tuple[PaperScore, list[dict]]:
    """Score one paper; returns its counts and a matches.csv row per molecule on each side."""
    score = PaperScore(
        paper,
        n_gt=len(truth),
        n_output_raw=sum(p.rows for p in predicted.values()),
        n_output=len(predicted),
        n_invalid=sum(not p.valid for p in predicted.values()),
    )
    truth_list, predicted_list = list(truth.values()), list(predicted.values())
    predicted_blind = {p.stereo_blind for p in predicted_list if p.valid}
    truth_blind = {g.stereo_blind for g in truth_list}
    rows = []

    for g in truth_list:
        found = g.key in predicted
        nearest, similarity = (predicted[g.key], 1.0) if found else _nearest(g, predicted_list)
        blind_match = g.stereo_blind in predicted_blind
        score.tp += found
        score.tp_stereo_blind += blind_match
        score.sum_best_tanimoto += similarity
        if g.name_type == "local":
            score.n_gt_local += 1
            score.tp_local += found
        rows.append(_match_row(paper, "gt", "TP" if found else "FN", g, nearest, similarity, blind_match))

    for p in predicted_list:
        correct = p.key in truth
        nearest, similarity = (truth[p.key], 1.0) if correct else _nearest(p, truth_list)
        blind_match = p.valid and p.stereo_blind in truth_blind
        rows.append(_match_row(paper, "pred", "TP" if correct else "FP", p, nearest, similarity, blind_match))
    return score, rows


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _score_row(run: dict, score: PaperScore) -> dict:
    return {
        **{k: run[k] for k in ("run_id", "handle", "tool", "dataset")},
        "paper_id": score.paper_id,
        **{k: getattr(score, k) for k in ("n_gt", "n_output_raw", "n_output", "n_invalid", "tp", "n_gt_local")},
        **{k: _fmt(getattr(score, k)) for k in (
            "precision", "recall", "f1", "recall_stereo_blind", "recall_local_names", "mean_best_tanimoto")},
        "rdkit_version": rdBase.rdkitVersion,
    }


def _macro_row(run: dict, scores: list[PaperScore]) -> dict:
    """Equal-weight average across papers. Counts are summed, the same as the pooled row."""
    row = _score_row(run, PaperScore.pooled(scores))
    row["paper_id"] = "macro"
    for metric in ("precision", "recall", "f1", "recall_stereo_blind", "mean_best_tanimoto", "recall_local_names"):
        values = [getattr(s, metric) for s in scores if getattr(s, metric) is not None]
        row[metric] = _fmt(sum(values) / len(values) if values else None)
    return row


def load_run(run_dir: Path) -> dict:
    """Read run.json, filling in handle and tool from the folder names if they're missing."""
    path = run_dir / "run.json"
    if not path.exists():
        raise ScoringError(f"{path} is missing")
    try:
        meta = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ScoringError(f"{path} isn't valid JSON: {e}") from e
    for key in ("task", "dataset"):
        if not meta.get(key):
            raise ScoringError(f"{path} needs a {key!r} field")
    try:
        score_threshold = float(meta.get("score_threshold") or 0.0)
    except (TypeError, ValueError):
        raise ScoringError(f"{path}: score_threshold must be a number") from None
    run_dir = run_dir.resolve()
    return {
        "run_id": run_dir.name,
        "handle": meta.get("handle") or run_dir.parent.name,
        # run_id is <date>_<tool>_<dataset>
        "tool": meta.get("tool") or "_".join(run_dir.name.split("_")[1:-1]),
        "dataset": meta["dataset"],
        "task": meta["task"],
        "score_threshold": score_threshold,  # detect runs: confidence cut-off for precision and recall
    }


def score_run(run_dir: Path, ground_truth: Path | None = None, tags: Path = TAGS) -> list[dict]:
    """Score one run folder, write scores.csv and matches.csv into it, and return the score rows."""
    run = load_run(run_dir)
    if run["dataset"] in BOX_DATASETS:
        import score_boxes  # it imports this module, so load it only when needed
        root = ground_truth if ground_truth and ground_truth.is_dir() else BOX_DATASETS[run["dataset"]]
        return score_boxes.score_run(run_dir, run, root, run["score_threshold"])[1]
    if run["task"] != "e2e":
        raise ScoringError(f"{run_dir}: dataset {run['dataset']!r} only has e2e scoring, not {run['task']!r}")
    gt_path = ground_truth or GROUND_TRUTH.get(run["dataset"])
    if gt_path is None:
        raise ScoringError(f"{run_dir}: no ground truth is set up for dataset {run['dataset']!r}; pass --gt")
    if not gt_path.exists():
        raise ScoringError(f"ground truth not found at {gt_path}; see data/README.md")

    truth = load_ground_truth(gt_path, load_tags(tags))
    predicted = load_predictions(run_dir / "predictions.csv", truth.keys())
    scores, matches = [], []
    for paper in sorted(truth, key=_paper_order):
        score, rows = score_paper(paper, truth[paper], predicted.get(paper, {}))
        scores.append(score)
        matches.extend(rows)

    rows = [_score_row(run, s) for s in scores]
    rows += [_macro_row(run, scores), _score_row(run, PaperScore.pooled(scores))]
    _write_csv(run_dir / "scores.csv", SCORE_COLUMNS, rows)
    _write_csv(run_dir / "matches.csv", MATCH_COLUMNS, matches)
    return rows


def find_runs(results_dir: Path = RESULTS) -> list[Path]:
    return sorted(p.parent for p in results_dir.glob("*/*/predictions.csv"))


def summary_name(run: dict) -> str:
    """summary.csv for e2e runs on the internal papers (task 1.5); one file per task and dataset otherwise."""
    if (run["task"], run["dataset"]) == ("e2e", "internal"):
        return "summary.csv"
    return f"summary_{run['task']}_{run['dataset']}.csv"


def score_all(results_dir: Path = RESULTS, ground_truth: Path | None = None,
              tags: Path = TAGS) -> tuple[list[dict], list[str]]:
    """Score every run under results_dir and write the summary files. Returns the rows and any errors."""
    groups: dict[str, list[dict]] = {"summary.csv": []}
    errors = []
    for run_dir in find_runs(results_dir):
        try:
            run = load_run(run_dir)
            groups.setdefault(summary_name(run), []).extend(score_run(run_dir, ground_truth, tags))
        except ScoringError as e:
            errors.append(str(e))
    for name, rows in groups.items():
        _write_csv(results_dir / name, list(rows[0]) if rows else SCORE_COLUMNS, rows)
    return [r for rows in groups.values() for r in rows], errors


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _print_scores(rows: list[dict]) -> None:
    if not rows:
        return
    print(f"\n{rows[0]['handle']}/{rows[0]['run_id']}")
    if "paper_id" not in rows[0]:  # a box-dataset run: one row of metrics
        skip = {"run_id", "handle", "tool", "dataset"}
        print("  " + "  ".join(f"{k}={v}" for k, v in rows[0].items() if k not in skip))
        return
    print(f"{'paper':<8}{'n_gt':>6}{'output':>8}{'tp':>6}{'precision':>11}{'recall':>9}")
    for r in rows:
        print(f"{r['paper_id']:<8}{r['n_gt']:>6}{r['n_output']:>8}{r['tp']:>6}{r['precision']:>11}{r['recall']:>9}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("runs", nargs="*", type=Path, help="run folders to score")
    parser.add_argument("--all", action="store_true",
                        help="score every run under benchmarks/results/ and write the summary files")
    parser.add_argument("--gt", type=Path, help="ground-truth CSV to use for every run, or a folder for a box "
                        "dataset (default: the dataset's files under data/)")
    parser.add_argument("--tags", type=Path, default=TAGS, help="ground-truth tags (default: benchmarks/gt_tags.csv)")
    args = parser.parse_args(argv)
    if bool(args.runs) == args.all:
        parser.error("give run folders to score, or --all, but not both")

    if rdBase.rdkitVersion != RDKIT_VERSION:
        print(f"warning: RDKit {rdBase.rdkitVersion} is installed but scores use {RDKIT_VERSION}; "
              "canonical SMILES can differ between versions", file=sys.stderr)

    if args.all:
        summary, errors = score_all(RESULTS, args.gt, args.tags)
        for run_id in dict.fromkeys(r["run_id"] for r in summary):
            _print_scores([r for r in summary if r["run_id"] == run_id])
        for path in sorted(RESULTS.glob("summary*.csv")):
            print(f"wrote {path.relative_to(REPO)}")
    else:
        errors = []
        for run_dir in args.runs:
            try:
                _print_scores(score_run(run_dir, args.gt, args.tags))
            except ScoringError as e:
                errors.append(str(e))
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    # Run main() from the module named `score`, the one score_boxes imports, so that
    # both share one ScoringError class and errors from either are caught.
    import score
    sys.exit(score.main())
