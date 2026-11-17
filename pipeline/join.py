"""Joining a scaffold and its substituents into one molecule (the chemistry half of assembly).

assembly.py works out, for one table row, which scaffold drawing and which
cells belong together. This file does the RDKit work once that is known:

1. `match_positions` decides which scaffold `*` each table column fills.
2. `_place_piece` prepares each `*` for its cell: a one-point substituent, a
   two-point linker (the `*` is split so both neighbours can bond), or a ring
   atom (the `*` becomes that element).
3. `_add_fragments` gives each pair of `*` atoms that should meet the same
   atom-map number and puts all fragments into one RDKit molecule.
4. `_zip` bonds the numbered pairs with RDKit's `molzip` and checks that the
   result is one complete, valid molecule.

Every step raises `Abstain` with a reason instead of guessing.

AI disclosure: Claude Code wrote this file at Will's request, for his review.
It moved `join` and its helpers out of assembly.py and split `join` into the
steps above without changing what it returns.
"""
from __future__ import annotations

from rdkit import Chem

from pipeline.stage_io import attachment_points, parse_smiles
from pipeline.substituents import same_label

RING = "ring:"  # a piece that replaces an in-ring `*` with an atom: "ring:N" or "ring:C:*Cl"

# (scaffold `*` indices, fragment SMILES) for one fragment to bond on. A
# substituent has one index; a linker has two, one per end.
Bond = tuple[list[int], str]


class Abstain(Exception):
    """This row cannot be assembled with certainty; the message is the recorded reason."""


# Step 1: which `*` does each column fill?

def _match_by_label(points: list[Chem.Atom], headings: list[str], labels: dict[int, str]) -> list[int] | None:
    """Match columns to stars by drawn label (`Ra` to `R[a]`), or None if any column is not a unique match."""
    matched = []
    for heading in headings:
        hits = [atom.GetIdx() for atom in points if same_label(heading, labels.get(atom.GetIdx(), ""))]
        if len(hits) != 1:
            return None
        matched.append(hits[0])
    return matched if len(set(matched)) == len(matched) else None


def _match_by_number(points: list[Chem.Atom], positions: list[int]) -> list[int]:
    """Match R1, R2 columns to `[1*]`, `[2*]` stars, or abstain if a number is repeated or missing."""
    numbers = [atom.GetIsotope() for atom in points]
    if len(set(positions)) != len(positions):
        raise Abstain("two table columns name the same R position")
    missing = [f"R{p}" for p in positions if p not in numbers]
    if missing:
        raise Abstain(f"scaffold reading has no {', '.join(missing)}")
    return [points[numbers.index(p)].GetIdx() for p in positions]


def match_positions(scaffold: Chem.Mol, positions: list[int | None],
                    headings: list[str] | None = None, labels: dict[int, str] | None = None) -> list[int]:
    """Choose the scaffold `*` atom for each table column, or abstain.

    `positions` holds each R column's number (1 for R1) or None for an
    unnumbered heading such as R or Ra. Returns one atom index per column.
    Three cases are unambiguous, tried in this order: the reader kept each `*`'s
    drawn label (`labels`, atom index to label) and it names the column; the
    stars are numbered and every column has a number; there is one star and
    one column.
    """
    points = attachment_points(scaffold)
    if labels and headings:
        matched = _match_by_label(points, headings, labels)
        if matched is not None:
            return matched
    numbers = [atom.GetIsotope() for atom in points]  # readers write R1 as [1*]
    numbered = all(numbers) and len(set(numbers)) == len(numbers)
    if numbered and all(position is not None for position in positions):
        return _match_by_number(points, positions)
    if len(points) == 1 and len(positions) == 1:
        return [points[0].GetIdx()]
    raise Abstain(f"cannot tell which column fills which attachment point "
                  f"({len(points)} points, {len(positions)} R columns, numbers do not match)")


# Step 2: prepare each `*` for the piece that fills it.

def _split_linker_point(mol: Chem.RWMol, index: int) -> int:
    """Give a two-neighbour `*` a twin, one per neighbour, so a linker can bond to both.

    Returns the twin's index. The star must not be in a ring (that would be a
    ring atom, not a linker) and both bonds must be single.
    """
    star = mol.GetAtomWithIdx(index)
    bonds = list(star.GetBonds())
    if star.IsInRing() or len(bonds) != 2 or any(b.GetBondType() != Chem.BondType.SINGLE for b in bonds):
        raise Abstain("linker position is not a two-neighbour chain atom")
    other = bonds[1].GetOtherAtomIdx(index)
    twin = mol.AddAtom(Chem.Atom(0))
    mol.RemoveBond(index, other)
    mol.AddBond(twin, other, Chem.BondType.SINGLE)
    return twin


def _fill_ring_atom(mol: Chem.RWMol, index: int, piece: str) -> list[Bond]:
    """Turn an in-ring `*` into the element a ring-atom column names (`ring:N`).

    A piece such as `ring:C:*Cl` also hangs a substituent on that atom; it is
    returned as a bond to make later. Returns no bonds otherwise.
    """
    element, _, fragment = piece[len(RING):].partition(":")
    star = mol.GetAtomWithIdx(index)
    if not star.IsInRing():
        raise Abstain("ring-atom column fills a star that is not in a ring")
    star.SetAtomicNum(Chem.GetPeriodicTable().GetAtomicNumber(element))
    star.SetIsotope(0)
    star.SetNumExplicitHs(0)
    star.SetNoImplicit(False)
    if not fragment:
        return []
    handle = mol.AddAtom(Chem.Atom(0))
    mol.AddBond(index, handle, Chem.BondType.SINGLE)
    return [([handle], fragment)]


def _attach_fragment(mol: Chem.RWMol, index: int, piece: str) -> Bond:
    """Pair a substituent (one `*`) with an end star, or a linker (two `*`) with a chain star.

    Abstains when the fragment's number of `*` does not fit the star's
    position: a linker on an end, or a substituent between two atoms.
    """
    star = mol.GetAtomWithIdx(index)
    fragment = parse_smiles(piece)
    points = len(attachment_points(fragment)) if fragment is not None else 0
    if points == 2 and star.GetDegree() == 2:
        return [index, _split_linker_point(mol, index)], piece
    if points == 1 and star.GetDegree() == 1:
        return [index], piece
    if points == 2:
        raise Abstain(f"linker {piece!r} fills an end position")
    raise Abstain(f"substituent {piece!r} is not a one-point fragment"
                  if star.GetDegree() == 1 else
                  f"substituent {piece!r} fills a position between two atoms")


def _place_piece(mol: Chem.RWMol, index: int, piece: str) -> list[Bond]:
    """Prepare the star at `index` for its piece; returns the fragment bonds still to make."""
    if piece.startswith(RING):
        return _fill_ring_atom(mol, index, piece)
    return [_attach_fragment(mol, index, piece)]


# Steps 3 and 4: number the pairs, combine, and zip.

def _add_fragments(mol: Chem.RWMol, bonds: list[Bond]) -> Chem.RWMol:
    """Add every fragment to `mol`, giving each scaffold star and its fragment end one shared map number.

    `molzip` later bonds the two atoms that share a number. Isotopes (the `[1*]`
    of R1) are cleared so they do not end up on the product.
    """
    number = 0
    for stars, piece in bonds:
        fragment = parse_smiles(piece)
        for star_index, end in zip(stars, attachment_points(fragment)):
            number += 1
            for atom in (mol.GetAtomWithIdx(star_index), end):
                atom.SetAtomMapNum(number)
                atom.SetIsotope(0)
        mol = Chem.RWMol(Chem.CombineMols(mol, fragment))
    return mol


def _zip(mol: Chem.RWMol) -> str:
    """Bond the numbered pairs with `molzip`; return canonical SMILES or abstain if it is not one full molecule."""
    try:
        zipped = Chem.molzip(mol)
        # Re-parsing folds an explicit [H] substituent back into its neighbour.
        product = parse_smiles(Chem.MolToSmiles(zipped))
    except Exception as error:  # molzip and sanitization raise on impossible valences
        raise Abstain(f"joined pieces are not a valid molecule ({type(error).__name__})") from error
    if product is None:
        raise Abstain("joined pieces are not a valid molecule")
    unfilled = len(attachment_points(product))
    if unfilled:
        raise Abstain(f"{unfilled} attachment point(s) of the scaffold have no table column")
    return Chem.MolToSmiles(product)


def join(scaffold_smiles: str, pieces: list[tuple[int | None, str]],
         headings: list[str] | None = None, labels: dict[int, str] | None = None) -> str:
    """Fill a scaffold's `*` atoms from the table and return canonical SMILES.

    `pieces` is a list of (R number or None, piece), where a piece is a fragment
    SMILES with one `*` (a substituent), two `*` (a linker; its scaffold `*`
    must sit between two atoms) or `ring:<element>[:<fragment>]` (a ring atom
    replacing an in-ring `*`). `headings` and `labels` let columns be matched to
    stars by their drawn labels (see match_positions). Raises Abstain if the
    result is not one complete, valid molecule.
    """
    scaffold = parse_smiles(scaffold_smiles)
    if scaffold is None:
        raise Abstain("scaffold reading is not valid SMILES")
    if not attachment_points(scaffold):
        raise Abstain("scaffold reading has no attachment point")
    targets = match_positions(scaffold, [position for position, _ in pieces], headings, labels)

    combined = Chem.RWMol(scaffold)
    for atom in attachment_points(combined):
        atom.SetAtomMapNum(0)
    # Ring atoms and linker twins only change or append atoms, so `targets` stays valid.
    bonds = [bond for index, (_, piece) in zip(targets, pieces)
             for bond in _place_piece(combined, index, piece)]
    return _zip(_add_fragments(combined, bonds))
