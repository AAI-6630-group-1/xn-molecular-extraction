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
    "*CC": ["Et", "C2H5", "CH2CH3", "CH2-CH3", "ethyl"],
    "*CCC": ["nPr", "n-Pr", "Pr", "propyl"],
    "*C(C)C": ["iPr", "i-Pr", "CH(CH3)2"],
    "*C1CC1": ["cPr", "c-Pr", "cyclopropyl", "cyclo-prop", "c-prop"],
    "*CCCC": ["nBu", "n-Bu", "Bu"],
    "*CC(C)C": ["iBu", "i-Bu", "CH2-iprop", "CH2-iPr", "isobutyl"],
    "*CCC(C)C": ["(CH2)2-iprop", "(CH2)2-iPr", "isopentyl"],
    "*C1CCCCC1": ["cHex", "c-Hex", "c-hexyl", "cyclohexyl"],
    "*C(C)(C)C": ["tBu", "t-Bu", "C(CH3)3"],
    "*C(F)(F)F": ["CF3"],
    "*CCC(F)(F)F": ["(CH2)2-CF3", "CH2CH2CF3"],
    "*CC(C)=O": ["CH2-C(O)-CH3", "CH2COCH3"],
    "*CC(C)O": ["CH2-C(OH)-CH3", "CH2CH(OH)CH3"],
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
    "*c1ccccc1": ["Ph", "C6H5", "phenyl"],
    "*Cc1ccccc1": ["Bn", "CH2Ph", "benzyl"],
    # Fluorobenzyls as paper 19 writes them; (o), (m), (p) give the F position.
    "*Cc1ccccc1F": ["CH2-(o)F-phenyl", "2-F-Bn"],
    "*Cc1cccc(F)c1": ["CH2-(m)F-phenyl", "3-F-Bn"],
    "*Cc1ccc(F)cc1": ["CH2-(p)F-phenyl", "4-F-Bn"],
}
FRAGMENTS = {name: smiles for smiles, names in _FRAGMENTS.items() for name in names}

_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")
_LEADING_BOND = "-–—−‒ "  # "-F" and "–OCH3" print the bond to the scaffold
# R, R1, R^1, R' and Ra. Headings such as X or Ar are left out: they can mean
# something other than a substituent, and a wrong join is worse than an abstention.
_POSITION = re.compile(r"(?:R\^?(\d{1,2})|R[a-z]?)'{0,2}")


def _clean(text: str) -> str:
    return (text or "").translate(_SUBSCRIPTS).replace("′", "'").strip()


def text_fragment(text: str) -> str | None:
    """Return the fragment SMILES for a substituent written as text, or None.

    Matching is exact and case-sensitive after removing a leading bond dash
    and spaces, so `-F`, `OCH₃` and `CF3` resolve but `4-F-Ph` does not. The
    one pattern rule is a straight chain written as `nC<n>H<2n+1>`.
    Ambiguous spellings stay out on purpose: `-ethylphenyl` (paper 19, 12l)
    could be phenethyl or 4-ethylphenyl, so that row abstains.
    """
    cleaned = _clean(text).lstrip(_LEADING_BOND).replace(" ", "")
    if cleaned in FRAGMENTS:
        return FRAGMENTS[cleaned]
    return _n_alkyl(cleaned)


# A straight chain written as a formula with the n- prefix: nC5H11 is n-pentyl.
# The hydrogen count must be 2n+1, so a typo or a ring (cC6H11) does not match.
_N_ALKYL = re.compile(r"n-?C(\d{1,2})H(\d{1,2})")


def _n_alkyl(text: str) -> str | None:
    match = _N_ALKYL.fullmatch(text)
    if not match:
        return None
    carbons, hydrogens = int(match.group(1)), int(match.group(2))
    if carbons < 1 or hydrogens != 2 * carbons + 1:
        return None
    return "*" + "C" * carbons


def column_position(heading: str) -> tuple[bool, int | None]:
    """Classify a table heading as (is an attachment column, its R number).

    `R1` gives (True, 1). `R` and `Ra` give (True, None): they name a varied
    position without a number. `Compd`, `IC50 (nM)` and `X` give (False, None).
    """
    match = _POSITION.fullmatch(_clean(heading).replace(" ", ""))
    if not match:
        return False, None
    return True, int(match.group(1)) if match.group(1) else None
