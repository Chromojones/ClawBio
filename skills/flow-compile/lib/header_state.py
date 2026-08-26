"""Which of four states did this FASTQ arrive in, and what params follow?

``fastq_headers.inspect_header_lines()`` answers with two booleans, ``(has_rbc,
barcode_in_header)``. That cannot express the four states an eCLIP FASTQ actually arrives in,
and the gap has teeth. Measured against the RBP ENCODE project on Flow:

===================  ============================================================
execution param      actual header
===================  ============================================================
``encode_eclip=false``  ``@HWI-D00611:153:…:25252 2:N:0:GAATTCGTTAATCTTA``
``encode_eclip=true``   ``@TAAAG:HWI-D00611:119:…:90397 2:N:0:TCCGGAGATATAGCCT``
===================  ============================================================

The second is ``eclipdemux`` output with the randomer **prepended to the title** — confirmed a
randomer, not a fixed barcode: 5 nt, 949 distinct values across 5,371 reads, base composition
within 3.1–15.2 of even.

``inspect_header_lines`` returns ``(False, False)`` for it — **the same answer it gives a raw
header**. A derivation trusting that sets ``move_umi_to_header=true`` and re-extracts five
bases from a read whose randomer is already in the header: five real bases of insert are
stripped and deduplication keys on sequence that is not the UMI. Nothing errors.

It also returns ``(True, False)`` for **both** ``:rbc:`` forms, so the mid- versus end-of-header
distinction that decides ``encode_eclip`` is not derivable from it.

Both docs were wrong in the same direction. ``SKILL.md`` said "eCLIP + ``:rbc:`` →
``encode_eclip=true``", ignoring position. ``reference/eclip-analysis-params.md`` fixed that but
added "Never set ``encode_eclip=true`` without ``:rbc:``" — which the live ENCODE data
contradicts, since the portal's own files carry a prepended randomer and no ``:rbc:`` at all.

Pure. Story: FAILURES.md#eclip-header-states
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lib.fastq_headers import RBC_TAG
from lib.protocol import ECLIP_FAMILY
from lib.results import Verdict

#: Raw instrument header; the randomer is still on the read and must be extracted.
RAW = "raw"
#: `eclipdemux` output — randomer prepended to the title (`@NNNNN:instrument:…`).
RANDOMER_PREFIX = "randomer_prefix"
#: ENCODE portal layout — `:rbc:` mid-header, the read name continues after the randomer.
RBC_MID = "rbc_mid"
#: `:rbc:` terminates the header. Typical iCLIP; NOT the ENCODE layout.
RBC_END = "rbc_end"

#: A prepended randomer: `@<ACGTN run>:` before anything instrument-shaped.
_PREFIX_RE = re.compile(r"^@([ACGTN]{3,15}):(?=.)")


def classify_header(header: str) -> str:
    """Which state does this single header line show?"""
    header = (header or "").strip()
    # Reuse `fastq_headers.RBC_TAG`: the tag is not always colon-delimited on the left.
    # GSE297587 appends it straight onto the index field (`…:N:0:1rbc:TAGGATAAA`), so a
    # literal ":rbc:" misses it. The lookbehind still refuses `rbc` inside a word.
    match = RBC_TAG.search(header)
    if match:
        after = header[match.end():]
        # The ENCODE layout keeps going after the randomer — a ` 1:N:0:INDEX` comment field
        # follows. iCLIP ends there.
        return RBC_MID if (" " in after or ":" in after) else RBC_END
    if _PREFIX_RE.match(header):
        return RANDOMER_PREFIX
    return RAW


@dataclass
class HeaderStateResult:
    ok: bool
    state: str = ""
    reason: str = ""
    counts: dict | None = None

    def verdict(self) -> Verdict:
        return Verdict(self.ok, self.reason, evidence=dict(self.counts or {}))


def classify_headers(headers: list[str]) -> HeaderStateResult:
    """Classify a sample of headers, refusing anything but a unanimous answer.

    Mixed states mean the files were not produced the same way. Taking a majority would apply
    one file's parameters to another file's reads, which is precisely the failure the state
    machine exists to prevent. No headers is no evidence — defaulting to ``RAW`` would extract
    from a file that had already been extracted.
    """
    seen = [classify_header(h) for h in headers if str(h or "").strip()]
    if not seen:
        return HeaderStateResult(
            False, reason="no headers sampled — cannot classify; do not assume raw",
        )
    counts: dict[str, int] = {}
    for state in seen:
        counts[state] = counts.get(state, 0) + 1
    if len(counts) > 1:
        return HeaderStateResult(
            False,
            reason=(
                f"mixed header states across the sample: {counts}. The files were not "
                f"produced the same way; classify and parameterise them separately."
            ),
            counts=counts,
        )
    return HeaderStateResult(True, state=seen[0], counts=counts)


def params_for_state(state: str, *, experimental_method: str) -> dict[str, str]:
    """The CLIP-pipeline parameters implied by a header state.

    ``encode_eclip`` is gated on BOTH the assay family and the layout: it is an eCLIP-family
    setting, and within that family it follows the layout rather than the mere presence of a
    ``:rbc:`` token.
    """
    is_eclip = str(experimental_method or "").strip().lower() in ECLIP_FAMILY
    encode = "true" if (is_eclip and state in (RBC_MID, RANDOMER_PREFIX)) else "false"

    if state == RAW:
        return {"move_umi_to_header": "true", "umi_separator": "_", "encode_eclip": encode}
    if state == RANDOMER_PREFIX:
        # Already extracted; re-extracting would strip real insert bases.
        return {"move_umi_to_header": "false", "umi_separator": ":", "encode_eclip": encode}
    return {"move_umi_to_header": "false", "umi_separator": "rbc:", "encode_eclip": encode}
