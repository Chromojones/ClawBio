"""Which of four states a CLIP FASTQ header is in, and the pipeline parameters that follow.

Raw, prepended randomer (`eclipdemux`), `:rbc:` mid-header (ENCODE portal) and `:rbc:` at the
end (iCLIP) need different UMI handling; treating a prepended randomer as raw strips five bases
of real insert. Pure.

Story: FAILURES.md#eclip-header-states
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
#: ENA's rendering, `@<run>.<n> <original name>`: the state is in the original name.
_ENA_RE = re.compile(r"^@[SED]RR\d+\.\d+\s+(\S.*)$")


def classify_header(header: str) -> str:
    """Which state does this single header line show?"""
    header = (header or "").strip()
    ena = _ENA_RE.match(header)
    if ena:
        header = "@" + ena.group(1)
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
    """Classify a sample of headers, refusing anything but a unanimous answer: mixed states mean the
    files were produced differently, and no headers is no evidence.
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

    `encode_eclip` runs `encode_moveumi`, which moves the first colon-delimited field of the read
    name to the end as the UMI — right only for a prepended randomer. On a `:rbc:` header that
    field is the instrument name, which would become a UMI constant across the library.

    Story: FAILURES.md#encode-moveumi
    """
    is_eclip = str(experimental_method or "").strip().lower() in ECLIP_FAMILY
    encode = "true" if (is_eclip and state == RANDOMER_PREFIX) else "false"

    if state == RAW:
        return {"move_umi_to_header": "true", "umi_separator": "_", "encode_eclip": encode}
    if state == RANDOMER_PREFIX:
        # Already extracted; re-extracting would strip real insert bases.
        return {"move_umi_to_header": "false", "umi_separator": ":", "encode_eclip": encode}
    return {"move_umi_to_header": "false", "umi_separator": "rbc:", "encode_eclip": encode}
