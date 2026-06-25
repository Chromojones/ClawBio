"""Infer Flow purification_target__annotation (tag/fusion on protein target)."""

from __future__ import annotations

import re

# Flow display combines purification_target + annotation as GENE:annotation (e.g. QKI:c3xFLAG-HBH).
C_TERM_3XFLAG_HBH = "c3xFLAG-HBH"


def characteristic_value(characteristics: list[str], *prefixes: str) -> str:
    for item in characteristics:
        lower = item.lower()
        for prefix in prefixes:
            if lower.startswith(prefix.lower()):
                return item.split(":", 1)[1].strip()
    return ""


def _expression_vector(characteristics: list[str]) -> str:
    return characteristic_value(characteristics, "expression vector:")


def _clip_antibody(characteristics: list[str]) -> str:
    return characteristic_value(characteristics, "clip antibody:")


def infer_purification_target_annotation(
    *,
    title: str,
    characteristics: list[str],
    experimental_method: str,
    protein_target: str,
) -> str:
    """
    Flow annotation sub-field on purification_target.

    Format: terminal prefix (c/n) + tag, hyphen for composite tags — e.g. c3xFLAG-HBH.
    Empty when endogenous antibody IP (FLASHendo) with no fusion tag.
    """
    expr = _expression_vector(characteristics)
    clip_ab = _clip_antibody(characteristics).lower()
    method = (experimental_method or "").upper()

    if not expr or expr.lower() in {"hbh tag", "empty vector", "vector only"}:
        return ""

    expr_lower = expr.lower()
    if "gfp" in expr_lower and not protein_target:
        return ""

    # uvCLAP / FLASHtagged: C-terminal 3xFLAG-HBH transgenes, pulled with anti-FLAG
    uses_flag_ip = "flag" in clip_ab
    tagged_construct = bool(re.search(r"\b3x?flag|3fhbh|flag-hbh|flag.?hbh", expr_lower, re.I))
    if uses_flag_ip or tagged_construct or method == "UVCLAP":
        if uses_flag_ip or tagged_construct or "hbh" in expr_lower or method == "UVCLAP":
            return C_TERM_3XFLAG_HBH

    # Explicit tag in vector name (e.g. hQKI-A with FLAG pull — still 3FHBH platform)
    if uses_flag_ip:
        return C_TERM_3XFLAG_HBH

    return ""
