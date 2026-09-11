"""Only an accession match proves a study is already on Flow.

A query's weight is read from its shape: an SRA/ENA accession names one experiment and is
decisive; a target or title word is context, shown for review. A failed accession query leaves
the answer inconclusive.

Fixture: GSE75418, whose only hit was `SHSY` in an unrelated project.

Story: FAILURES.md#study-check
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.study_check import summarise_hits  # noqa: E402

HIT = {"projects": [{"id": "808005400407594329", "name": "Global-iCLIP_05_26"}],
       "samples": [{"id": "911173746376357146", "name": "TDP43_Hs_SHSY5Y_Cytoplasm"}],
       "data": []}
EMPTY = {"projects": [], "samples": [], "data": [], "executions": []}
ON_FLOW = {"projects": [], "samples": [],
           "data": [{"id": "1", "filename": "SRX1453676_SRR1.fastq.gz"}]}


class TestTheGse75418FalsePositive:
    """Verbatim: only the generic extra term matched, on an unrelated project."""

    def test_an_extra_only_match_is_not_already_present(self):
        results = {"SRX1453676": EMPTY, "SRX1453677": EMPTY, "SAFB1": EMPTY, "SHSY": HIT}
        assert summarise_hits(results).already_present is False

    def test_the_incidental_match_is_still_shown_not_hidden(self):
        """Suppressing it would hide a real neighbouring project from the reader."""
        text = summarise_hits({"SRX1453676": EMPTY, "SAFB1": EMPTY, "SHSY": HIT}).describe()
        assert "808005400407594329" in text
        assert "proceed" in text.lower()


class TestAnAccessionMatchIsDecisive:
    def test_one_accession_hit_means_already_present(self):
        hits = summarise_hits({"SRX1453676": ON_FLOW, "SRX1453677": EMPTY, "SAFB1": EMPTY})
        assert hits.already_present is True
        assert hits.decisive_matches == ["SRX1453676"]

    def test_run_and_ena_accessions_are_decisive_too(self):
        for query in ("SRR5099205", "ERX123456", "DRR000001"):
            assert summarise_hits({query: HIT}).already_present is True, query


class TestATargetMatchIsContextNotProof:
    def test_a_target_hit_alone_does_not_block(self):
        """Two labs CLIPping the same protein is normal science, not a duplicate."""
        results = {"SRX1453676": EMPTY, "SRX1453677": EMPTY, "SAFB1": HIT}
        assert summarise_hits(results).already_present is False

    def test_but_it_is_reported_for_review(self):
        text = summarise_hits({"SRX1453676": EMPTY, "SAFB1": HIT}).describe()
        assert "SAFB1" in text
        assert "related" in text.lower()


class TestFailedQueries:
    def test_failed_queries_surface(self):
        hits = summarise_hits({"SRX1453676": None})
        assert "SRX1453676" in hits.failed_queries
        assert "failed" in hits.describe().lower()

    def test_a_failed_accession_query_is_not_a_clean_bill(self):
        """The decisive query erroring must not read as 'not present'."""
        hits = summarise_hits({"SRX1453676": None, "SAFB1": EMPTY})
        assert hits.inconclusive is True
        assert "inconclusive" in hits.describe().lower()

    def test_a_failed_target_query_is_not_inconclusive(self):
        assert summarise_hits({"SRX1453676": EMPTY, "SAFB1": None}).inconclusive is False
