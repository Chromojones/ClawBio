"""Flow organism codes: the one table, and normalisation onto it.

The API takes the two-letter code only; the Latin and common names it returns are for
display and are rejected on submission. `metadata_validate` reads the same table.
"""

from __future__ import annotations

import re

#: Flow's organism vocabulary, from `GET /api/organisms`.
ORGANISM_CODES: dict[str, str] = {
    "Hs": "Homo sapiens",
    "Mm": "Mus musculus",
    "Rn": "Rattus norvegicus",
    "Dr": "Danio rerio",
    "Dm": "Drosophila melanogaster",
    "Sc": "Saccharomyces cerevisiae",
    "Ec": "Escherichia coli",
    "Gg": "Gallus gallus",
    "At": "Arabidopsis thaliana",
    "Vf": "Vibrio fischeri",
}

#: Latin names, common names, lowercase codes and NCBI taxids, mapped to the code.
ORGANISM_ALIASES: dict[str, str] = {
    **{latin.lower(): code for code, latin in ORGANISM_CODES.items()},
    **{code.lower(): code for code in ORGANISM_CODES},
    "human": "Hs", "mouse": "Mm", "rat": "Rn", "zebrafish": "Dr", "drosophila": "Dm",
    "fruit fly": "Dm", "yeast": "Sc", "e. coli": "Ec", "chicken": "Gg", "arabidopsis": "At",
    "v. fischeri": "Vf",
    "9606": "Hs", "10090": "Mm", "10116": "Rn", "7955": "Dr", "7227": "Dm", "4932": "Sc",
    "562": "Ec", "9031": "Gg", "3702": "At", "668": "Vf",
}


def normalize_organism(raw: str) -> str:
    """The Flow code for ``raw``, or "" when it names no Flow organism."""
    token = str(raw or "").strip()
    if not token:
        return ""
    if token in ORGANISM_CODES:
        return token
    return ORGANISM_ALIASES.get(re.sub(r"\s+", " ", token.lower()), "")


def validate_organism_column(values: list[str]) -> list[str]:
    """Errors for an Organism column: every cell must be a Flow code."""
    errors: list[str] = []
    for i, val in enumerate(values, start=1):
        if not val:
            errors.append(f"row {i}: Organism is empty")
        elif val not in ORGANISM_CODES:
            hint = ORGANISM_ALIASES.get(str(val).strip().lower())
            errors.append(f"row {i}: Organism must be a Flow organism code, not {val!r}"
                          + (f" — use {hint!r}" if hint else f" ({', '.join(ORGANISM_CODES)})"))
    return errors
