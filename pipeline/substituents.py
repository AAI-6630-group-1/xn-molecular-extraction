"""Turn the text of an R-group table (headings and cells) into chemistry.

Two lookups, both deliberately small and exact:

- `column_position("R1")` says whether a table heading names an attachment
  position, and which numbered one.
- `text_fragment("OMe")` returns the substituent as a SMILES fragment with one
  `*` where it bonds to the scaffold (`*OC`).

Anything not in the table returns None and the row abstains. A wrong guess here
would export a wrong molecule with nothing downstream to catch it, so there is
no fuzzy matching and no name-to-structure lookup (the interface contract
disables name lookup).

AI disclosure: Claude Code wrote this file at Will's request, for his review.
"""
from __future__ import annotations

import re

# Fragment SMILES, attachment point first. One spelling per line group; the
# test suite checks that each parses and has exactly one `*`.
_FRAGMENTS = {
    "*[H]": ["H"],
    "*[2H]": ["D"],
    "*F": ["F"], "*Cl": ["Cl"], "*Br": ["Br"], "*I": ["I"],
    "*O": ["OH"], "*S": ["SH"], "*N": ["NH2"],
    "*C#N": ["CN"],
    "*[N+](=O)[O-]": ["NO2"],
    "*C": ["Me", "CH3"],
    "*CC": ["Et", "C2H5", "CH2CH3"],
    "*CCC": ["nPr", "n-Pr", "Pr"],
    "*C(C)C": ["iPr", "i-Pr", "CH(CH3)2"],
    "*C1CC1": ["cPr", "c-Pr", "cyclopropyl"],
    "*CCCC": ["nBu", "n-Bu", "Bu"],
    "*CC(C)C": ["iBu", "i-Bu"],
    "*C(C)(C)C": ["tBu", "t-Bu", "C(CH3)3"],
    "*C(F)(F)F": ["CF3"],
    "*C(F)F": ["CHF2", "CF2H"],
    "*OC": ["OMe", "MeO", "OCH3", "CH3O"],
    "*OCC": ["OEt", "EtO", "OC2H5"],
    "*OC(C)C": ["OiPr", "O-iPr"],
    "*OC(F)(F)F": ["OCF3"],
    "*OC(F)F": ["OCHF2"],
    "*Oc1ccccc1": ["OPh", "PhO"],
    "*OCc1ccccc1": ["OBn", "BnO"],
    "*OC(C)=O": ["OAc", "AcO"],
    "*C(C)=O": ["Ac", "COMe", "COCH3"],
    "*C=O": ["CHO"],
    "*C(=O)O": ["COOH", "CO2H"],
    "*C(=O)OC": ["COOMe", "CO2Me", "CO2CH3"],
    "*C(=O)OCC": ["COOEt", "CO2Et"],
    "*C(N)=O": ["CONH2"],
    "*NC": ["NHMe", "NHCH3"],
    "*N(C)C": ["NMe2", "N(CH3)2"],
    "*NC(C)=O": ["NHAc"],
    "*C(=O)OC(C)(C)C": ["Boc"],
    "*NC(=O)OC(C)(C)C": ["NHBoc"],
    "*SC": ["SMe", "SCH3"],
    "*S(C)(=O)=O": ["SO2Me", "SO2CH3", "Ms"],
    "*S(N)(=O)=O": ["SO2NH2"],
    "*c1ccccc1": ["Ph", "C6H5"],
    "*Cc1ccccc1": ["Bn", "CH2Ph"],
}
FRAGMENTS = {name: smiles for smiles, names in _FRAGMENTS.items() for name in names}

_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")
_LEADING_BOND = "-–—−‒ "  # "-F" and "–OCH3" print the bond to the scaffold
# R, R1, R^1, R', Ra, and the single letters papers use for a varied position.
_POSITION = re.compile(r"(?:R\^?(\d{1,2})|R[a-z]?|X|Y|Z|Ar)'{0,2}")


def _clean(text: str) -> str:
    return (text or "").translate(_SUBSCRIPTS).replace("′", "'").strip()


def text_fragment(text: str) -> str | None:
    """Return the fragment SMILES for a substituent written as text, or None.

    Matching is exact and case-sensitive after removing a leading bond dash
    and spaces, so `-F`, `OCH₃` and `CF3` resolve but `4-F-Ph` does not.
    """
    cleaned = _clean(text).lstrip(_LEADING_BOND).replace(" ", "")
    return FRAGMENTS.get(cleaned)


def column_position(heading: str) -> tuple[bool, int | None]:
    """Classify a table heading as (is an attachment column, its R number).

    `R1` gives (True, 1). `R`, `Ra` and `X` give (True, None): they name a
    varied position without a number. `Compd` and `IC50 (nM)` give (False, None).
    """
    match = _POSITION.fullmatch(_clean(heading).replace(" ", ""))
    if not match:
        return False, None
    return True, int(match.group(1)) if match.group(1) else None
