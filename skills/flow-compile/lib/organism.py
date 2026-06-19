"""Normalize organism to Flow two-letter codes (Hs, Mm, Gg only)."""

from __future__ import annotations

import re

ALLOWED_ORGANISMS = frozenset({"Hs", "Mm", "Gg"})

_ORGANISM_ALIASES: dict[str, str] = {
    "homo sapiens": "Hs",
    "human": "Hs",
    "hs": "Hs",
    "9606": "Hs",
    "mus musculus": "Mm",
    "mouse": "Mm",
    "mm": "Mm",
    "10090": "Mm",
    "gallus gallus": "Gg",
    "chicken": "Gg",
    "gg": "Gg",
    "9031": "Gg",
}


def normalize_organism(raw: str) -> str:
    """Return Hs, Mm, or Gg. Never return full scientific names."""
    if not raw or not str(raw).strip():
        return ""
    token = str(raw).strip()
    if token in ALLOWED_ORGANISMS:
        return token
    # Already a code embedded in longer text
    upper = token.upper()
    if upper in ALLOWED_ORGANISMS:
        return upper
    key = re.sub(r"\s+", " ", token.lower())
    return _ORGANISM_ALIASES.get(key, "")


def validate_organism_column(values: list[str]) -> list[str]:
    """Return list of validation errors for an Organism column."""
    errors: list[str] = []
    for i, val in enumerate(values, start=1):
        if not val:
            errors.append(f"row {i}: Organism is empty")
            continue
        if val not in ALLOWED_ORGANISMS:
            errors.append(f"row {i}: Organism must be Hs, Mm, or Gg (got {val!r})")
        if " " in val or "sapiens" in val.lower() or "musculus" in val.lower():
            errors.append(f"row {i}: full scientific name not allowed (got {val!r})")
    return errors
