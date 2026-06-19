"""Fetch GEO sample page text for barcode evidence extraction."""

from __future__ import annotations

import re
from pathlib import Path

import requests

_GEO_ACC = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
_TIMEOUT = 15


def fetch_geo_sample_text(gsm: str) -> str:
    gsm = gsm.strip().upper()
    if not re.match(r"^GSM\d+$", gsm):
        raise ValueError(f"Invalid GSM accession: {gsm}")
    resp = requests.get(_GEO_ACC, params={"acc": gsm, "targ": "self"}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def load_geo_sample_text(gsm: str, cache_path: Path | None = None) -> tuple[str, str]:
    """Return (text, source_label). Use cache file when present."""
    if cache_path and cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace"), f"cache:{cache_path.name}"
    text = fetch_geo_sample_text(gsm)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
    return text, f"geo:{gsm}"


def strip_html(html: str) -> str:
    """Crude tag strip for GEO HTML — sufficient for regex extraction."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text
