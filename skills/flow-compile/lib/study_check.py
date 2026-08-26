"""Is this study fetchable, and is it already on Flow?

Two questions asked back to back before anything is built, previously in two modules with two
``Check`` dataclasses between them.

The second exists because ``import_check.find_already_present()`` is not enough on its own: it
compares the sheet's sample *names*, which we choose, so a study uploaded earlier under a
different naming convention reports "none (clean import)" and is imported a second time.
Searching Flow for the study's own identifiers catches what name comparison cannot.

Pure. Story: FAILURES.md#study-check
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lib.results import ERROR, Finding as Check, INFO, Verdict, WARNING  # noqa: F401

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

#: Result buckets that say something about the DATA. `users` and `groups` can match a protein
#: name by coincidence and mean nothing about whether the study is present.
_DATA_BUCKETS = ("projects", "samples", "data", "executions")

#: Targets shared across studies — querying them returns every eCLIP project on the platform.
_GENERIC_TARGETS = {"SMINPUT", "INPUT", "IGG", "GFP", "CONTROL", "NO ANTIBODY"}


def query_kinds(sheet_rows: list[dict], *, extra: list[str] | None = None) -> dict[str, str]:
    """Label each query by how much weight its match carries.

    Only an ``accession`` match proves this exact data is already on the platform. A
    ``target`` match means some study of that protein exists, which may well be a different
    paper — two labs CLIPping the same protein is normal and must not be blocked. ``extra``
    terms (cell lines, title words) match almost anything.
    """
    kinds: dict[str, str] = {}
    for row in sheet_rows:
        accession = str(row.get("accession", "")).strip()
        if accession:
            kinds[accession] = "accession"
    for row in sheet_rows:
        target = str(row.get("purification_target", "")).strip()
        if target and target.upper() not in _GENERIC_TARGETS:
            kinds.setdefault(target, "target")
    for term in extra or []:
        term = str(term).strip()
        if term:
            kinds.setdefault(term, "extra")
    return kinds


@dataclass
class Hits:
    """What a database-wide search found."""

    already_present: bool = False
    matched_queries: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)
    data: list[dict] = field(default_factory=list)
    failed_queries: list[str] = field(default_factory=list)
    total_queries: int = 0
    #: queries that matched, split by weight — only `decisive` blocks an import
    decisive_matches: list[str] = field(default_factory=list)
    related_matches: list[str] = field(default_factory=list)
    inconclusive: bool = False

    def describe(self) -> str:
        lines: list[str] = []
        if self.failed_queries:
            lines.append(
                f"{len(self.failed_queries)} search(es) FAILED and prove nothing: "
                f"{', '.join(self.failed_queries)}"
            )
        if not self.total_queries:
            lines.append(
                "no queries were run — this is not evidence the study is absent. "
                "Build queries from the sheet's accessions and targets."
            )
            return "\n".join(lines)
        if self.inconclusive:
            lines.append(
                "INCONCLUSIVE — an accession query failed, and accessions are the only "
                "decisive evidence. Re-run before importing."
            )
        if not self.already_present:
            lines.append(
                f"no accession match across {self.total_queries} quer(y/ies) — this study "
                f"does not appear to be on the platform; proceed."
            )
            if self.related_matches:
                lines.append(
                    f"  related hits worth a look (not duplicates): "
                    f"{', '.join(self.related_matches)} — review the project(s) below."
                )
                for project in self.projects:
                    lines.append(f"    project {project.get('id')}  {project.get('name','')}")
                for sample in self.samples[:5]:
                    lines.append(f"    sample  {sample.get('id')}  {sample.get('name','')}")
            return "\n".join(lines)

        lines.append(
            f"ALREADY PRESENT — accession(s) matched: {', '.join(self.decisive_matches)}"
        )
        for project in self.projects:
            lines.append(f"  project {project.get('id')}  {project.get('name','')}")
        for sample in self.samples[:10]:
            lines.append(f"  sample  {sample.get('id')}  {sample.get('name','')}")
        if len(self.samples) > 10:
            lines.append(f"  … and {len(self.samples) - 10} more sample(s)")
        for item in self.data[:5]:
            lines.append(f"  data    {item.get('id')}  {item.get('filename','')}")
        lines.append("Do NOT import. Open the project above and decide whether to extend it.")
        return "\n".join(lines)


def build_search_queries(sheet_rows: list[dict], *, extra: list[str] | None = None) -> list[str]:
    """Terms worth searching, in the order most likely to be decisive.

    Accessions first — they are unique to the study and survive inside deposited filenames.
    Then real protein targets. Control targets are skipped: ``SMInput`` matches every eCLIP
    study on the platform and would bury a true positive in noise.

    ``geo`` and PubMed ids are deliberately absent — the endpoint does not index them, so
    including them would only pad a clean result with queries that can never match.
    """
    queries: list[str] = []
    for row in sheet_rows:
        accession = str(row.get("accession", "")).strip()
        if accession and accession not in queries:
            queries.append(accession)
    for row in sheet_rows:
        target = str(row.get("purification_target", "")).strip()
        if target and target.upper() not in _GENERIC_TARGETS and target not in queries:
            queries.append(target)
    for term in extra or []:
        term = str(term).strip()
        if term and term not in queries:
            queries.append(term)
    return queries


def summarise_hits(results: dict[str, dict | None], *, kinds: dict[str, str] | None = None) -> Hits:
    """Fold ``{query: search_response}`` into a verdict.

    A ``None`` response marks a query that errored. That is the opposite of an empty result
    and is reported separately — swallowing it would let a failed lookup read as "absent",
    the same conflation that once turned a broken listing into a silent no-op upload.
    """
    hits = Hits(total_queries=len(results))
    for query, response in results.items():
        if response is None:
            hits.failed_queries.append(query)
            continue
        matched = False
        for bucket in _DATA_BUCKETS:
            for item in response.get(bucket) or []:
                matched = True
                if bucket == "projects" and item not in hits.projects:
                    hits.projects.append(item)
                elif bucket == "samples" and item not in hits.samples:
                    hits.samples.append(item)
                elif bucket == "data" and item not in hits.data:
                    hits.data.append(item)
        if matched:
            hits.matched_queries.append(query)
            kind = (kinds or {}).get(query, "accession")   # no kinds -> old conservative behaviour
            if kind == "accession":
                hits.decisive_matches.append(query)
            else:
                hits.related_matches.append(query)
    if kinds:
        hits.inconclusive = any(kinds.get(q) == "accession" for q in hits.failed_queries)
    hits.already_present = bool(hits.decisive_matches)
    return hits


def search_url(query: str, base: str = "https://app.flow.bio/api") -> str:
    """The search URL, so callers do not each rediscover that the parameter is ``q``."""
    return f"{base}/search?q={query}"
