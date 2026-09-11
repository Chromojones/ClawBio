"""Only an accession match proves a study is already on Flow.

``accession``
    decisive: `SRX1453676` names one experiment.
``target``
    context: another lab may have CLIPped the same protein.
``extra``
    advisory: cell lines and title words match anything.

Fixture: GSE75418, whose only hit was `SHSY` in an unrelated project.

Story: FAILURES.md#study-check
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.study_check import (  # noqa: E402
    build_search_queries,
    query_kinds,
    summarise_hits,
)

SHEET = [
    {"accession": "SRX1453676", "purification_target": "SAFB1"},
    {"accession": "SRX1453677", "purification_target": "SAFB1"},
]
HIT = {"projects": [{"id": "808005400407594329", "name": "Global-iCLIP_05_26"}],
       "samples": [{"id": "911173746376357146", "name": "TDP43_Hs_SHSY5Y_Cytoplasm"}],
       "data": []}
EMPTY = {"projects": [], "samples": [], "data": [], "executions": []}


class TestQueryKinds:
    def test_accessions_targets_and_extras_are_labelled(self):
        kinds = query_kinds(SHEET, extra=["SHSY"])
        assert kinds["SRX1453676"] == "accession"
        assert kinds["SAFB1"] == "target"
        assert kinds["SHSY"] == "extra"

    def test_kinds_cover_exactly_the_built_queries(self):
        queries = build_search_queries(SHEET, extra=["SHSY"])
        assert set(query_kinds(SHEET, extra=["SHSY"])) == set(queries)


class TestTheGse75418FalsePositive:
    """Verbatim: only the generic extra term matched, on an unrelated project."""

    def test_an_extra_only_match_is_not_already_present(self):
        results = {"SRX1453676": EMPTY, "SRX1453677": EMPTY, "SAFB1": EMPTY, "SHSY": HIT}
        hits = summarise_hits(results, kinds=query_kinds(SHEET, extra=["SHSY"]))
        assert hits.already_present is False

    def test_the_incidental_match_is_still_shown_not_hidden(self):
        """Suppressing it would hide a real neighbouring project from the reader."""
        results = {"SRX1453676": EMPTY, "SAFB1": EMPTY, "SHSY": HIT}
        text = summarise_hits(results, kinds=query_kinds(SHEET, extra=["SHSY"])).describe()
        assert "808005400407594329" in text
        assert "proceed" in text.lower()


class TestAnAccessionMatchIsDecisive:
    def test_one_accession_hit_means_already_present(self):
        results = {"SRX1453676": {"projects": [], "samples": [],
                                  "data": [{"id": "1", "filename": "SRX1453676_SRR1.fastq.gz"}]},
                   "SRX1453677": EMPTY, "SAFB1": EMPTY}
        hits = summarise_hits(results, kinds=query_kinds(SHEET))
        assert hits.already_present is True
        assert "SRX1453676" in hits.matched_queries


class TestATargetMatchIsContextNotProof:
    def test_a_target_hit_alone_does_not_block(self):
        """Two labs CLIPping the same protein is normal science, not a duplicate."""
        results = {"SRX1453676": EMPTY, "SRX1453677": EMPTY, "SAFB1": HIT}
        hits = summarise_hits(results, kinds=query_kinds(SHEET))
        assert hits.already_present is False

    def test_but_it_is_reported_for_review(self):
        results = {"SRX1453676": EMPTY, "SAFB1": HIT}
        text = summarise_hits(results, kinds=query_kinds(SHEET)).describe()
        assert "SAFB1" in text
        assert "review" in text.lower() or "related" in text.lower()


class TestBackwardsCompatibility:
    def test_without_kinds_every_match_still_counts(self):
        """With no `kinds`, every match counts: the conservative default."""
        assert summarise_hits({"anything": HIT}).already_present is True

    def test_failed_queries_still_surface(self):
        hits = summarise_hits({"SRX1453676": None}, kinds=query_kinds(SHEET))
        assert "SRX1453676" in hits.failed_queries
        assert "failed" in hits.describe().lower()

    def test_a_failed_accession_query_is_not_a_clean_bill(self):
        """The decisive query erroring must not read as 'not present'."""
        hits = summarise_hits({"SRX1453676": None, "SAFB1": EMPTY}, kinds=query_kinds(SHEET))
        assert "inconclusive" in hits.describe().lower()
