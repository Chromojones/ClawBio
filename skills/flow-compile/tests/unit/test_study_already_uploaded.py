"""Search all of Flow for the study, not the project just created.

A new project is empty by construction, and uploaders never share sample names (GSE80202 was
imported twice). `GET /api/search?q=` (`q`, not `query`) indexes sample names, project names and
data filenames, measured live:

===================  ==========================================
`q=SRR5099205`       `data: 4`   → hit, via the filename
`q=SRX2415967`       `data: 4`   → hit, via the filename
`q=Zfp871`           `projects: 1, samples: 4`
`q=GSM2424749`       nothing — GEO ids are not indexed
`q=28157508`         nothing — PubMed ids are not indexed
===================  ==========================================

So the queries are accessions and protein names.

Story: FAILURES.md#study-check
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.study_check import (  # noqa: E402
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
        """`q=GSM2424749` and `q=28157508` return nothing; querying them only makes a clean result look
        better evidenced.
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

    def test_a_target_hit_on_projects_is_reported_for_review(self):
        """A target match is context: it names the project without blocking the import."""
        results = {"ZFP871": {"projects": [{"id": "929598612629946169",
                                            "name": "Multilayered control of alternative splicing"}],
                              "samples": [{"id": "680624169803349319",
                                           "name": "Zfp871_N2A_Mm_c14_FLAG_rep1"}],
                              "data": []}}
        hits = summarise_hits(results)
        assert hits.already_present is False
        assert hits.related_matches == ["ZFP871"]
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
        # asserts the claim, not the phrasing
        assert "does not appear to be on the platform" in hits.describe().lower()

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
