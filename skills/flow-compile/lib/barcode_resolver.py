"""Stage 3: protocol-aware 5' barcode resolution."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

TAG_PATTERN = re.compile(r"3'\s*tag:\s*([ACGTNRY]+)", re.I)
FIVE_TAG_PATTERN = re.compile(r"5'\s*tag:\s*([ACGTNRY]+)", re.I)
ADAPTER_FLASH = re.compile(r"NNBBN[A-Z]+NN", re.I)
UMI_N_PATTERN = re.compile(r"\b(N{8,20})\b")
ICLIP2_HINT = re.compile(r"\biclip2?\b", re.I)


@dataclass
class BarcodeResolution:
    gsm: str
    five_prime: str
    three_prime: str
    protocol: str
    confidence: str
    sources: list[str] = field(default_factory=list)
    notes: str = ""


def detect_protocol(samples: dict[str, dict[str, Any]]) -> str:
    blob = " ".join(
        str(sample.get("extract_protocol_ch1", "")) for sample in samples.values()
    )
    if ADAPTER_FLASH.search(blob):
        return "flash"
    if ICLIP2_HINT.search(blob):
        return "iclip2"
    return "generic"


def extract_three_prime_tag(characteristics: list[str]) -> str:
    for item in characteristics:
        match = TAG_PATTERN.search(item)
        if match:
            return match.group(1).upper()
    return ""


def extract_five_prime_tag(characteristics: list[str]) -> str:
    for item in characteristics:
        match = FIVE_TAG_PATTERN.search(item)
        if match:
            return match.group(1).upper()
    return ""


def resolve_flash(samples: dict[str, dict[str, Any]]) -> list[BarcodeResolution]:
    adapter = "NNBBNTTTTTTNN"
    for sample in samples.values():
        match = ADAPTER_FLASH.search(sample.get("extract_protocol_ch1", ""))
        if match:
            adapter = match.group(0).upper()
            break

    resolutions: list[BarcodeResolution] = []
    for gsm, sample in samples.items():
        characteristics = sample.get("characteristics", [])
        three_tag = extract_three_prime_tag(characteristics)
        sources: list[str] = []
        five_prime = ""
        confidence = "low"
        if three_tag:
            sources.append(f"3' tag {three_tag}")
            five_prime = f"NNBBN{three_tag}NN"
            confidence = "high" if "NNBBN" in adapter else "medium"
            sources.append("extract_protocol NNBBN…NN grammar")
        resolutions.append(
            BarcodeResolution(
                gsm=gsm,
                five_prime=five_prime,
                three_prime=three_tag,
                protocol="flash",
                confidence=confidence,
                sources=sources,
            )
        )
    return resolutions


def resolve_iclip2(samples: dict[str, dict[str, Any]]) -> list[BarcodeResolution]:
    """iCLIP2 / hnRNPH-style: long UMI runs (e.g. 16N) from protocol or override."""
    default_umi = "NNNNNNNNNNNNNNNN"
    protocol_text = " ".join(
        str(s.get("extract_protocol_ch1", "")) for s in samples.values()
    )
    umi_match = UMI_N_PATTERN.search(protocol_text)
    if umi_match:
        default_umi = umi_match.group(1)

    resolutions: list[BarcodeResolution] = []
    for gsm, sample in samples.items():
        characteristics = sample.get("characteristics", [])
        five_explicit = extract_five_prime_tag(characteristics)
        sources: list[str] = []
        if five_explicit:
            five_prime = five_explicit
            confidence = "high"
            sources.append(f"5' tag {five_explicit}")
        else:
            five_prime = default_umi
            confidence = "medium" if umi_match else "low"
            sources.append("iclip2 protocol UMI pattern")
        resolutions.append(
            BarcodeResolution(
                gsm=gsm,
                five_prime=five_prime,
                three_prime=extract_three_prime_tag(characteristics),
                protocol="iclip2",
                confidence=confidence,
                sources=sources,
            )
        )
    return resolutions


def resolve_barcodes(samples: dict[str, dict[str, Any]], protocol: str | None = None) -> list[BarcodeResolution]:
    proto = protocol or detect_protocol(samples)
    if proto == "flash":
        return resolve_flash(samples)
    if proto == "iclip2":
        return resolve_iclip2(samples)
    return resolve_flash(samples)


def barcode_audit_json(resolutions: list[BarcodeResolution]) -> list[dict[str, Any]]:
    return [asdict(r) for r in resolutions]
