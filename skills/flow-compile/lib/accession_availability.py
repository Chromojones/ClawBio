"""Is the study's data actually public? Ask first, before any metadata work.

AUTS2 (PMID 41278797) reads as an ideal candidate — eCLIP of a new protein in human neural
progenitors — and names three GEO accessions in its Data Availability statement. All three
are private, **scheduled for release on 07 Aug 2029**. Discovering that after the literature
dig rather than before it wasted the entire dig.

A preprint's Data Availability statement is a *promise*, not a fact. Accessions are commonly
reserved at submission and released on publication, so a named GSE proves only that the
authors intend to deposit. One request settles it::

    GET https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=<GSE>&targ=self&form=text&view=brief

**The signal is the response format, not its wording.** GEO returns SOFT text for a released
series and an HTML page for an embargoed one. Sniffing for the word "private" would misread a
public series whose summary happens to discuss private data; asking "did I get SOFT back"
cannot.

Three outcomes are worth telling apart, because each implies a different next move:

===================  ==================================================================
released             proceed
private + a date     weeks away → wait; years away → email the authors, or drop it
not found            a typo, or the accession was withdrawn
===================  ==================================================================

This module is pure; the caller supplies the response body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: "…is currently private and is scheduled to be released on Aug 07, 2029."
_PRIVATE_RE = re.compile(
    r"is currently private.*?released on\s+([A-Z][a-z]{2}\s+\d{1,2},\s*\d{4})",
    re.I | re.S,
)
_PRIVATE_NO_DATE_RE = re.compile(r"is currently private", re.I)
_NOT_FOUND_RE = re.compile(r"could not be found", re.I)


@dataclass
class Availability:
    """What one accession lookup established."""

    accession: str
    public: bool
    sample_count: int = 0
    release_date: str = ""
    pubmed: str = ""
    reason: str = ""

    def describe(self) -> str:
        if self.public:
            return f"{self.accession}: public, {self.sample_count} sample(s) — proceed."
        if self.release_date:
            return (
                f"{self.accession}: NOT public — {self.reason}. Nothing can be imported "
                f"until {self.release_date}; ask the authors for a reviewer token, or "
                f"choose another study."
            )
        return f"{self.accession}: NOT public — {self.reason}."


def parse_geo_response(accession: str, body: str) -> Availability:
    """Classify a GEO ``form=text`` response.

    A released series answers in SOFT (``^SERIES`` / ``!Series_…``); anything else is an
    HTML page explaining why not. An empty body is treated as *not* public — a failed fetch
    read as success is how a phantom result gets into a report.
    """
    text = (body or "").strip()
    if not text:
        return Availability(accession, public=False, reason="empty response — the fetch failed")

    is_soft = bool(re.search(r"^\^SERIES|^!Series_", text, re.M))
    if not is_soft:
        match = _PRIVATE_RE.search(text)
        if match:
            date = re.sub(r"\s+", " ", match.group(1)).strip()
            return Availability(
                accession, public=False, release_date=date,
                reason=f"private until {date}",
            )
        if _PRIVATE_NO_DATE_RE.search(text):
            return Availability(accession, public=False, reason="private, no release date given")
        if _NOT_FOUND_RE.search(text):
            return Availability(accession, public=False, reason="not found in GEO")
        return Availability(
            accession, public=False,
            reason="GEO returned HTML rather than SOFT — not a released series",
        )

    samples = len(re.findall(r"^!Series_sample_id", text, re.M))
    pubmed_match = re.search(r"^!Series_pubmed_id\s*=\s*(\d+)", text, re.M)
    pubmed = pubmed_match.group(1) if pubmed_match else ""
    if samples == 0:
        return Availability(
            accession, public=False, pubmed=pubmed,
            reason="released but lists no samples — nothing to import",
        )
    return Availability(accession, public=True, sample_count=samples, pubmed=pubmed)


def geo_url(accession: str) -> str:
    """The lookup URL, so callers do not each hand-assemble the query string."""
    return (
        "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
        f"?acc={accession}&targ=self&form=text&view=brief"
    )
