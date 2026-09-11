"""The resolved 5' barcode of one sample, as `04_annotate` consumes it."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BarcodeResolution:
    gsm: str
    five_prime: str
    three_prime: str
    protocol: str
    confidence: str
    sources: list[str] = field(default_factory=list)
    notes: str = ""
