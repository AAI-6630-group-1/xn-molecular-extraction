"""Tests for benchmarks/readers.py. Run with `pytest benchmarks/tests`.

These don't load any model weights; the readers themselves were checked by
reproducing committed predictions (benchmarks/willdaly/README.md).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import readers  # noqa: E402


def test_unknown_reader_names_the_choices():
    with pytest.raises(ValueError, match="choose from molscribe, molglyph"):
        readers.load_reader("not-a-reader")


def test_patch_molscribe_applies_and_can_be_repeated():
    chem = pytest.importorskip("molscribe.chemistry")
    readers.patch_molscribe()
    patched = chem._expand_functional_group
    # The patched function has no source file, so a second real patch would fail; it must be a no-op.
    readers.patch_molscribe()
    assert chem._expand_functional_group is patched
    assert "bond_orders" in patched.__code__.co_varnames
