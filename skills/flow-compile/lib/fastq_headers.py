"""Where the `rbc:` UMI tag sits in sampled FASTQ read headers."""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The `rbc:` UMI tag is not always colon-delimited on the left. GSE297587 (LARP6 iCLIP)
#: appends it straight onto the index field — `…:N:0:1rbc:TAGGATAAA` — so a `:rbc:` pattern
#: reports "no UMI in header" and the pipeline is told to extract it again, stripping bases
#: that were already removed. Accept any non-alphabetic left delimiter (`:`, digit, `_`,
#: start of string) while still refusing `rbc` embedded in a word such as `sorbc:`.
RBC_TAG = re.compile(r"(?<![A-Za-z])rbc:", re.I)
UNDERSCORE_BARCODE = re.compile(r"_([ACGTNacgtn]+)(?:/|\s|$)")


@dataclass
class HeaderInspection:
    """Result of inspecting sampled read headers."""

    has_rbc: bool
    barcode_in_header: bool
    sample_headers: list[str]
    fastq_files: list[str]
    notes: str = ""
    #: True when the UMI tag sits in the header's COMMENT (after the first space) rather
    #: than the read name. Aligners drop the comment, so the UMI never reaches the BAM and
    #: dedup fails
    umi_in_comment: bool = False

    @property
    def barcode_already_extracted(self) -> bool:
        return self.has_rbc


def inspect_header_lines(headers: list[str]) -> tuple[bool, bool]:
    """Return (has_rbc, barcode_in_header_via_underscore)."""
    at_lines = [h for h in headers if h.startswith("@")]
    has_rbc = any(RBC_TAG.search(h) for h in at_lines)
    has_underscore = any(UNDERSCORE_BARCODE.search(h) for h in at_lines)
    return has_rbc, has_underscore


