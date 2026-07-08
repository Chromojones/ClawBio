"""Stage 2: GEO series matrix parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Barcode-like tokens: ≥4 chars, only A/C/G/T/N, at least one N (UMI/run positions).
_BARCODE_TOKEN = re.compile(r"\b([ACGTN]{4,24})\b", re.I)
# Fixed 4-mer cores in processed-file names (e.g. GSE105082 _rsem_CGGA. → NNNCGGANNN variant).
_REPLICATE_CORE = re.compile(r"_rsem_([ACGT]{4})\.", re.I)
# Exclude tokens that are all fixed bases with no N (likely adapter fragments, not patterns).
_MIN_N_COUNT = 1


def scan_barcode_patterns(text: str) -> list[str]:
    """
    Find literal barcode/UMI patterns in free text (GEO matrix cells, SDRF fields).

    Returns de-duplicated uppercase patterns sorted longest-first (prefer specific
    patterns over short N-runs). Only tokens with at least one ``N`` are kept.
    """
    if not text:
        return []
    seen: set[str] = set()
    hits: list[str] = []
    for match in _BARCODE_TOKEN.finditer(text):
        token = match.group(1).upper()
        if token.count("N") < _MIN_N_COUNT:
            continue
        if token in seen:
            continue
        seen.add(token)
        hits.append(token)
    hits.sort(key=len, reverse=True)
    return hits


def scan_replicate_barcode_cores(text: str) -> list[str]:
    """
    Fixed 4-mer cores from supplementary/processed filenames (no N required).

    Example: ``GSM2817677_rsem_CGGA.trimmed...`` → ``CGGA`` (maps to paper barcode ``NNNCGGANNN``).
    """
    if not text:
        return []
    seen: set[str] = set()
    hits: list[str] = []
    for match in _REPLICATE_CORE.finditer(text):
        core = match.group(1).upper()
        if core in seen:
            continue
        seen.add(core)
        hits.append(core)
    return hits


def _collect_sample_barcode_hints(sample: dict[str, Any]) -> list[str]:
    """Aggregate barcode-like tokens from all string fields on one GSM sample."""
    parts: list[str] = []
    for key, value in sample.items():
        if key in ("gsm", "characteristics", "barcode_hints"):
            continue
        if isinstance(value, str) and value.strip():
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(v) for v in value if v)
    return scan_barcode_patterns(" ".join(parts))


def parse_geo_matrix(path: Path) -> dict[str, Any]:
    """Parse GEO series matrix into series metadata and per-GSM sample dicts."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    series: dict[str, str] = {}
    sample_rows: list[tuple[str, list[str]]] = []
    gsm_row: list[str] = []

    for line in lines:
        if not line.startswith("!"):
            continue
        parts = line.split("\t")
        key = parts[0]
        values = [v.strip().strip('"') for v in parts[1:]]
        if key.startswith("!Series_"):
            series[key.replace("!Series_", "").lower()] = values[0] if values else ""
        elif key == "!Sample_geo_accession":
            gsm_row = values
        elif key.startswith("!Sample_"):
            sample_rows.append((key.replace("!Sample_", ""), values))

    if not gsm_row:
        raise ValueError(f"No !Sample_geo_accession row in {path}")

    samples: dict[str, dict[str, Any]] = {
        gsm: {"gsm": gsm, "characteristics": []} for gsm in gsm_row
    }
    for field_name, values in sample_rows:
        if field_name == "geo_accession":
            continue
        for gsm, value in zip(gsm_row, values, strict=False):
            if field_name == "characteristics_ch1":
                samples[gsm]["characteristics"].append(value)
            else:
                existing = samples[gsm].get(field_name)
                if existing:
                    samples[gsm][field_name] = f"{existing} {value}".strip()
                else:
                    samples[gsm][field_name] = value

    for gsm, sample in samples.items():
        sample["barcode_hints"] = _collect_sample_barcode_hints(sample)
        core_parts = []
        for key, value in sample.items():
            if key in ("gsm", "characteristics", "barcode_hints", "replicate_barcode_cores"):
                continue
            if isinstance(value, str) and "supplementary" in key.lower():
                core_parts.append(value)
        sample["replicate_barcode_cores"] = scan_replicate_barcode_cores(" ".join(core_parts))

    return {"series": series, "samples": samples}
