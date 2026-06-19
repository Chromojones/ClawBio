"""Tests for organism normalization."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.organism import normalize_organism, validate_organism_column


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Homo sapiens", "Hs"),
        ("homo sapiens", "Hs"),
        ("human", "Hs"),
        ("Hs", "Hs"),
        ("Mus musculus", "Mm"),
        ("mouse", "Mm"),
        ("Mm", "Mm"),
        ("Gallus gallus", "Gg"),
    ],
)
def test_normalize_organism(raw, expected):
    assert normalize_organism(raw) == expected


def test_reject_unknown():
    assert normalize_organism("Danio rerio") == ""


def test_validate_rejects_full_name_in_column():
    errors = validate_organism_column(["Homo sapiens"])
    assert any("Hs, Mm, or Gg" in e for e in errors)
