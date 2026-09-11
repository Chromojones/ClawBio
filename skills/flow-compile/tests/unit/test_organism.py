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


def test_every_flow_organism_normalises_and_unknown_is_empty():
    assert normalize_organism("Danio rerio") == "Dr"
    assert normalize_organism("Drosophila melanogaster") == "Dm"
    assert normalize_organism("Klingon") == ""


def test_validate_rejects_full_name_in_column():
    errors = validate_organism_column(["Homo sapiens"])
    assert errors and all("code" in e for e in errors)
