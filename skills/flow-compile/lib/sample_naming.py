"""Flow-compatible sample naming from GEO metadata."""

from __future__ import annotations

import re


def sanitize_name_token(value: str) -> str:
    """Flow sample names must not contain spaces or special characters."""
    value = (value or "").strip()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^A-Za-z0-9_]", "", value)
    return value or "unknown"


def infer_replicate_label(title: str) -> str:
    """
  Derive RepN from GEO/SRA sample title.

  Examples:
    iCLIP-DHX9-1 -> Rep1
    iCLIP-DHX9-2 -> Rep2
    FLASH-STAU2_rep2 -> Rep2
    """
    title_lower = (title or "").lower().strip()
    if re.search(r"\brep\s*b\b", title_lower) or re.search(r"replicate\s*b", title_lower):
        return "Rep2"
    if re.search(r"\brep\s*a\b", title_lower) or re.search(r"replicate\s*a", title_lower):
        return "Rep1"
    if re.search(r"rep\s*2", title_lower) or re.search(r"replicate\s*2", title_lower):
        return "Rep2"
    if re.search(r"rep\s*1", title_lower) or re.search(r"replicate\s*1", title_lower):
        return "Rep1"
    match = re.search(r"[-_](\d+)\s*$", title.strip())
    if match:
        return f"Rep{match.group(1)}"
    return "Rep1"


def infer_replicate_number(title: str) -> int:
    label = infer_replicate_label(title)
    match = re.search(r"(\d+)$", label)
    return int(match.group(1)) if match else 1


def build_flow_sample_name(protein: str, cell: str, org: str, title: str, srr: str) -> str:
    rep = infer_replicate_label(title)
    parts = [
        sanitize_name_token(protein),
        sanitize_name_token(org),
        sanitize_name_token(cell),
        rep,
        sanitize_name_token(srr),
    ]
    return "_".join(p for p in parts if p)


def validate_flow_sample_name(name: str) -> list[str]:
    errors: list[str] = []
    if not name:
        errors.append("sample name is empty")
    if re.search(r"\s", name):
        errors.append("sample name must not contain spaces")
    if re.search(r"[^A-Za-z0-9_]", name):
        errors.append("sample name must use only letters, numbers, and underscores")
    return errors
