"""Infer Flow purification_target__annotation (tag/fusion on protein target)."""

from __future__ import annotations

import re

# Flow display combines purification_target + annotation as GENE:annotation (e.g. QKI:c3xFLAG-HBH).
C_TERM_3XFLAG_HBH = "c3xFLAG-HBH"
C_TERM_V5 = "cV5"


def characteristic_value(characteristics: list[str], *prefixes: str) -> str:
    for item in characteristics:
        lower = item.lower()
        for prefix in prefixes:
            if lower.startswith(prefix.lower()):
                return item.split(":", 1)[1].strip()
    return ""


#: Tags whose terminus can be read off a construct name. Longest first so `3xFLAG` is
#: preferred over `FLAG`.
_KNOWN_TAGS = ("3xFLAG-HBH", "3xFLAG", "FLAG", "GFP", "V5", "HA", "MYC", "HBH", "SNAP", "HALO")


def terminus_from_construct_name(text: str, protein_target: str) -> str:
    """`n`/`c` + tag from the order of tag and gene in a construct name: `myc-LARP6` → N-terminal,
    `LARP6-myc` → C-terminal. "" when the name lacks either, so the caller falls back to the
    C-terminal default.
    """
    target = str(protein_target or "").strip()
    blob = str(text or "")
    if not target or not blob:
        return ""
    for tag in _KNOWN_TAGS:
        # `myc-LARP6`, `mycLARP6`, `GFP-LARP6` — tag immediately before the gene.
        if re.search(rf"\b{re.escape(tag)}[-_ ]?{re.escape(target)}\b", blob, re.I):
            return f"n{tag}"
        # `LARP6-myc`, `LARP6myc`
        if re.search(rf"\b{re.escape(target)}[-_ ]?{re.escape(tag)}\b", blob, re.I):
            return f"c{tag}"
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
    extract_protocol: str = "",
) -> str:
    """The tag annotation for purification_target: terminal prefix (`c`/`n`) plus tag, e.g.
    `c3xFLAG-HBH`; empty for an endogenous IP.
    """
    expr = _expression_vector(characteristics)
    clip_ab = _clip_antibody(characteristics).lower()
    proto = (extract_protocol or "").lower()
    method = (experimental_method or "").upper()

    # Tethered eCLIP (e.g. GSE290281): V5-tagged RBPs pulled with anti-V5 — not FLAG.
    if "v5-antibody" in proto or "v5 antibody" in proto:
        return C_TERM_V5

    # Construct-name order is the first fallback when no terminus is stated: `myc-LARP6`
    # is N-terminal, `LARP6-myc` is C-terminal (GSE297587). Checked against the title, the
    # expression-vector characteristic and the protocol text.
    for text in (title, characteristic_value(characteristics, "expression vector:"), extract_protocol):
        inferred = terminus_from_construct_name(text, protein_target)
        if inferred:
            return inferred

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
