"""Has this study already been uploaded — anywhere on the platform?

GSE80202 was already on Flow as project ``929598612629946169``: public, all 7 samples, paper
attached. It was imported a second time regardless.

``import_preflight.find_already_present()`` ran first and reported *none (clean import)*. It
was accurate and worthless, for two compounding reasons:

1. **Scope.** It checks the *target* project. The target had been created seconds earlier, so
   it was empty by construction and the check could not have returned anything else. A
   pre-flight whose answer is fixed before it runs proves nothing.
2. **Key.** It matches sample *names*. The existing samples were ``Nacc1_N2A_Mm_rep1``; the
   incoming ones ``NACC1_N2A_Mm_endogenous_rep1_SRX2415967``. Two people never pick the same
   name, so name matching would have missed these even database-wide.

The durable key is what the data **is** — the run/experiment accession, which survives inside
the deposited filename — and the **target protein**.

``GET /api/search?q=<term>``. The parameter is ``q``; ``query`` returns
``{"error": {"q": ["This field is required"]}}``. Measured against the live instance:

===================  ==========================================
``q=SRR5099205``     ``data: 4``  → hit via the filename
``q=SRX2415967``     ``data: 4``  → hit via the filename
``q=Zfp871``         ``projects: 1, samples: 4``
``q=GSM2424749``     nothing — GEO ids are **not** indexed
``q=28157508``       nothing — PubMed ids are **not** indexed
===================  ==========================================

GSM and PMID are the obvious keys and both silently return empty, which is precisely how a
check comes to prove nothing while looking thorough. They are deliberately not queried.

This module is pure; the caller performs the searches and passes the responses in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Result buckets that say something about the DATA. `users` and `groups` can match a protein
#: name by coincidence and mean nothing about whether the study is present.
_DATA_BUCKETS = ("projects", "samples", "data", "executions")

#: Targets shared across studies — querying them returns every eCLIP project on the platform.
_GENERIC_TARGETS = {"SMINPUT", "INPUT", "IGG", "GFP", "CONTROL", "NO ANTIBODY"}


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
        if not self.already_present:
            lines.append(
                f"no match across {self.total_queries} quer(y/ies) — the study does not "
                f"appear to be on the platform."
            )
            return "\n".join(lines)

        lines.append(
            f"ALREADY PRESENT — {len(self.matched_queries)} of {self.total_queries} "
            f"quer(y/ies) matched: {', '.join(self.matched_queries)}"
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


def summarise_hits(results: dict[str, dict | None]) -> Hits:
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
    hits.already_present = bool(hits.matched_queries)
    return hits


def search_url(query: str, base: str = "https://app.flow.bio/api") -> str:
    """The search URL, so callers do not each rediscover that the parameter is ``q``."""
    return f"{base}/search?q={query}"
