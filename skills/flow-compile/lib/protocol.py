"""The CLIP protocol a study used, and what follows from it. Pure.

Detection order matters: `PAR-iCLIP` is tested before `PAR-CLIP` and `iCLIP`, which would each
match part of it. FLASH, uvCLAP and PAR-CLIP are detected so they can be refused by name.

Story: FAILURES.md#protocol-detection
"""

from __future__ import annotations

import re

#: Assays for which `encode_eclip` is meaningful. The single definition.
ECLIP_FAMILY = frozenset({"eclip", "seclip"})

#: Backwards-compatible alias for `pipeline_params.ECLIP_METHODS`.
ECLIP_METHODS = ECLIP_FAMILY

#: Protocols this skill detects but does not process.
UNSUPPORTED = frozenset({"FLASH", "uvCLAP", "PAR-CLIP"})

#: "flash-frozen" is boilerplate in extract protocols; strip it before matching FLASH.
_FLASH_FROZEN_RE = re.compile(r"\bflash[\s-]?frozen\b", re.I)

#: A method name may carry up to three lowercase letters of prefix (`seCLIP`, `irCLIP`),
#: itself anchored on a non-letter so prose words cannot bleed in.
_PFX = r"(?<![A-Za-z])[a-z]{0,3}"

#: (regex, method) in specificity order — a prefixed token can otherwise be claimed by a
#: shorter pattern. Do not reorder without reading the PAR-iCLIP note above.
_METHOD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"{_PFX}iclip2\b", re.I), "iCLIP2"),
    (re.compile(r"(?<![A-Za-z])ir[\s-]?clip\b", re.I), "irCLIP"),
    (re.compile(r"(?<![A-Za-z])se[\s-]?clip\b", re.I), "seCLIP"),
    (re.compile(rf"{_PFX}uvclap\b", re.I), "uvCLAP"),
    (re.compile(rf"{_PFX}par[\s-]?iclip\b", re.I), "PAR-iCLIP"),
    (re.compile(rf"{_PFX}par[\s-]?clip\b", re.I), "PAR-CLIP"),
    (re.compile(rf"{_PFX}hits[\s-]?clip\b", re.I), "HITS-CLIP"),
    (re.compile(rf"{_PFX}iclap\b", re.I), "iCLAP"),
    (re.compile(r"\bflash\b", re.I), "FLASH"),
    (re.compile(rf"{_PFX}eclip\b", re.I), "eCLIP"),
    (re.compile(rf"{_PFX}iclip\b", re.I), "iCLIP"),
]

#: The annotation column carrying the method.
_METHOD_COLUMN = "Experimental Method"


def is_eclip_method(method: str) -> bool:
    """Is this an eCLIP-family assay? The one definition."""
    return str(method or "").strip().lower() in ECLIP_FAMILY


def match_method(text: str) -> str:
    """The protocol named in ``text``, or ``""``."""
    blob = _FLASH_FROZEN_RE.sub(" ", text or "")
    for pattern, method in _METHOD_PATTERNS:
        if pattern.search(blob):
            return method
    return ""


def detect_method(protocol: str, series_title: str = "") -> str:
    """The protocol, preferring the series title over protocol prose, which often cites other
    protocols. An unknown protocol falls back to iCLIP and is surfaced by the metadata gate.
    """
    return match_method(series_title) or match_method(protocol) or "iCLIP"


def annotation_is_eclip(annotation) -> bool:
    """Does any row of this annotation carry an eCLIP-family method?

    Accepts a DataFrame or a list of mappings so callers need not import pandas.
    """
    if annotation is None:
        return False
    rows = annotation.to_dict("records") if hasattr(annotation, "to_dict") else annotation
    return any(is_eclip_method(str(r.get(_METHOD_COLUMN, ""))) for r in rows)


def is_supported(method: str) -> bool:
    """Can this skill process the protocol, as opposed to merely name it?"""
    return str(method or "").strip() not in UNSUPPORTED
