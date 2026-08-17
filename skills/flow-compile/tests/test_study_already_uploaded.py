"""Search the whole DATABASE for the study, not the project you just created.

GSE80202 was already on Flow as project `929598612629946169`, public, with all 7 samples and
the paper attached. It was imported again anyway.

`import_preflight.find_already_present()` ran and reported "none (clean import)". It was
telling the truth and was useless, for two compounding reasons:

1. **Scope.** It checks the *target* project. The target was a project created seconds
   earlier, so it was empty by construction — the check could not have returned anything
   else. A pre-flight whose answer is determined before it runs is theatre.
2. **Key.** It matches on sample *name*. The existing samples were named
   `Nacc1_N2A_Mm_rep1`; the incoming ones `NACC1_N2A_Mm_endogenous_rep1_SRX2415967`. Two
   uploaders never choose the same name, so name matching would have missed these even
   database-wide.

The durable key is what the data IS, not what someone called it: the **run/experiment
accession**, which appears in the deposited filename, and the **target protein**.

`GET /api/search?q=<term>` (note `q`, not `query` — `query` returns
`{"error": {"q": ["This field is required"]}}`) indexes sample names, project names, and
data filenames. Measured against the live instance:

===================  ==========================================
`q=SRR5099205`       `data: 4`   → hit, via the filename
`q=SRX2415967`       `data: 4`   → hit, via the filename
`q=Zfp871`           `projects: 1, samples: 4`
`q=GSM2424749`       nothing — GEO ids are NOT indexed
`q=28157508`         nothing — PubMed ids are NOT indexed
===================  ==========================================

So the queries that work are accessions and protein names. GSM and PMID look like obvious
keys and silently return nothing, which is exactly how a check ends up proving nothing.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.study_already_uploaded import (  # noqa: E402
    build_search_queries,
    summarise_hits,
)

SHEET = [
    {"accession": "SRX2415967", "name": "NACC1_N2A_Mm_endogenous_rep1_SRX2415967",
     "purification_target": "NACC1", "geo": "GSM2424749"},
    {"accession": "SRX1700551", "name": "ZFP871_N2A_Mm_clone63_rep1_SRX1700551",
     "purification_target": "ZFP871", "geo": "GSM2120777"},
    {"accession": "SRX2415969", "name": "SMInput_N2A_Mm_forNACC1_rep1_SRX2415969",
     "purification_target": "SMInput", "geo": "GSM2424751"},
]


class TestTheQueriesWeBuild:
    def test_every_accession_is_queried(self):
        queries = build_search_queries(SHEET)
        for accession in ("SRX2415967", "SRX1700551", "SRX2415969"):
            assert accession in queries

    def test_real_targets_are_queried(self):
        queries = build_search_queries(SHEET)
        assert "NACC1" in queries and "ZFP871" in queries

    def test_control_targets_are_not_queried(self):
        """`SMInput` would match every eCLIP study on the platform — pure noise."""
        assert "SMInput" not in build_search_queries(SHEET)

    def test_geo_and_pubmed_are_not_queried_because_they_are_not_indexed(self):
        """Measured: `q=GSM2424749` and `q=28157508` both return nothing.

        Including them would add queries that can only ever come back empty, making a
        clean result look better-evidenced than it is.
        """
        queries = build_search_queries(SHEET)
        assert "GSM2424749" not in queries
        assert "28157508" not in queries

    def test_extra_terms_can_be_supplied(self):
        """A study title catches a project even when nothing else does."""
        queries = build_search_queries(SHEET, extra=["Multilayered"])
        assert "Multilayered" in queries


class TestTheGse80202Regression:
    def test_an_accession_hit_on_data_is_reported(self):
        """Verbatim shape from the live endpoint — the filename carries the accession."""
        results = {"SRX2415967": {"users": [], "groups": [], "projects": [], "samples": [],
                                  "executions": [],
                                  "data": [{"id": "266861575136398856",
                                            "filename": "SRX2415967_SRR5099205.fastq.gz"}]}}
        hits = summarise_hits(results)
        assert hits.already_present is True
        assert "SRX2415967" in hits.matched_queries

    def test_a_target_hit_on_projects_is_reported(self):
        results = {"ZFP871": {"projects": [{"id": "929598612629946169",
                                            "name": "Multilayered control of alternative splicing"}],
                              "samples": [{"id": "680624169803349319",
                                           "name": "Zfp871_N2A_Mm_c14_FLAG_rep1"}],
                              "data": []}}
        hits = summarise_hits(results)
        assert hits.already_present is True
        assert "929598612629946169" in {p["id"] for p in hits.projects}

    def test_the_report_names_the_project_so_it_can_be_opened(self):
        results = {"ZFP871": {"projects": [{"id": "929598612629946169", "name": "Multilayered"}],
                              "samples": [], "data": []}}
        assert "929598612629946169" in summarise_hits(results).describe()


class TestACleanResult:
    def test_all_queries_empty_means_not_present(self):
        results = {"SRX999": {"projects": [], "samples": [], "data": [], "executions": []}}
        hits = summarise_hits(results)
        assert hits.already_present is False
        assert "no match" in hits.describe().lower()

    def test_user_and_group_hits_are_ignored(self):
        """A protein name matching a username says nothing about the data."""
        results = {"NACC1": {"users": [{"id": "1", "name": "nacc1fan"}],
                             "groups": [{"id": "2", "name": "NACC1 lab"}],
                             "projects": [], "samples": [], "data": []}}
        assert summarise_hits(results).already_present is False


class TestDegenerateInput:
    def test_no_queries_run_is_not_a_clean_bill(self):
        """Zero searches must not read as "I looked and found nothing"."""
        hits = summarise_hits({})
        assert hits.already_present is False
        assert "no queries" in hits.describe().lower()

    def test_a_failed_query_is_surfaced_not_swallowed(self):
        """`None` marks a query that errored — the opposite of an empty result."""
        hits = summarise_hits({"SRX1": None, "SRX2": {"projects": [], "samples": [], "data": []}})
        assert "SRX1" in hits.failed_queries
        assert "failed" in hits.describe().lower()
