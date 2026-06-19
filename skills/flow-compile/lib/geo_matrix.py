"""Stage 2: GEO series matrix parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
                samples[gsm][field_name] = value
    return {"series": series, "samples": samples}
