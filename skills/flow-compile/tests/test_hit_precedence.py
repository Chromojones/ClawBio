"""Only an ACCESSION match proves a study is already uploaded.

The first version of `summarise_hits` treated any non-empty bucket from any query as
"ALREADY PRESENT". Run against GSE75418 (SAFB1 in SH-SY5Y) it reported the study present on
the strength of a single match — for the term `SHSY`, which hit TDP43 and HNRNPA1 samples in
an unrelated project. All seven SRX accessions returned nothing.

That is the worse kind of wrong. A false negative loses a check; a false positive blocks
correct work and teaches the reader to click past the warning — the same reason
`execution_audit` was rewritten after it flagged every finished run.

The three query kinds carry completely different weight:

``accession``
    decisive. `SRX1453676` is unique to one experiment; if it is on the platform, this exact
    data is on the platform.
``target``
    contextual. `SAFB1` matching means *some* SAFB1 study exists — which may well be a
    different paper. Two labs CLIPping the same protein is normal and must not be blocked.
``extra``
    advisory only. Cell lines and title words match anything.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.study_already_uploaded import (  # noqa: E402
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
        """Callers that pass no `kinds` keep the old conservative behaviour."""
        assert summarise_hits({"anything": HIT}).already_present is True

    def test_failed_queries_still_surface(self):
        hits = summarise_hits({"SRX1453676": None}, kinds=query_kinds(SHEET))
        assert "SRX1453676" in hits.failed_queries
        assert "failed" in hits.describe().lower()

    def test_a_failed_accession_query_is_not_a_clean_bill(self):
        """The decisive query erroring must not read as 'not present'."""
        hits = summarise_hits({"SRX1453676": None, "SAFB1": EMPTY}, kinds=query_kinds(SHEET))
        assert "inconclusive" in hits.describe().lower()
