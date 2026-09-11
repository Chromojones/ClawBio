"""Ask the project what it holds before importing; a status note is not evidence.

A stale note on E-MTAB-2700 led to a re-import that made 48 samples in a 24-sample project. The
trimmed listing from `GET /projects/{id}/samples` suffices here: only names are needed.

Story: FAILURES.md#import-check
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_check import (  # noqa: E402
    find_already_present,
    names_from_listing,
)

SHEET = [
    {"accession": "ERX561234", "name": "APOBEC3G_CEMSS_Hs_T7_cell_rep1_ERR565167"},
    {"accession": "ERX561235", "name": "APOBEC3F_CEMSS_Hs_T7_cell_rep1_ERR565166"},
]

# Verbatim key set from the live listing endpoint — no `metadata` content, but names present.
LISTING = {
    "samples": [
        {"id": "111", "name": "APOBEC3G_CEMSS_Hs_T7_cell_rep1_ERR565167",
         "metadata": {}, "sample_type": "CLIP", "private": True},
    ]
}


class TestTheEmtab2700Regression:
    def test_a_name_already_in_the_project_is_reported(self):
        present = find_already_present(SHEET, names_from_listing(LISTING))
        assert present == ["APOBEC3G_CEMSS_Hs_T7_cell_rep1_ERR565167"]

    def test_an_empty_project_lets_the_import_proceed(self):
        assert find_already_present(SHEET, names_from_listing({"samples": []})) == []

    def test_every_name_present_means_the_import_is_entirely_redundant(self):
        listing = {"samples": [{"id": str(i), "name": r["name"], "metadata": {}}
                               for i, r in enumerate(SHEET)]}
        assert len(find_already_present(SHEET, names_from_listing(listing))) == len(SHEET)


class TestTheTrimmedListingIsCorrectHere:
    def test_names_survive_the_trimmed_shape(self):
        """Unlike verification, a pre-flight needs only names — so this endpoint is right."""
        assert names_from_listing(LISTING) == {"APOBEC3G_CEMSS_Hs_T7_cell_rep1_ERR565167"}

    def test_whitespace_around_a_name_does_not_hide_a_collision(self):
        listing = {"samples": [{"id": "1", "name": "  APOBEC3F_CEMSS_Hs_T7_cell_rep1_ERR565166 "}]}
        assert find_already_present(SHEET, names_from_listing(listing)) == [
            "APOBEC3F_CEMSS_Hs_T7_cell_rep1_ERR565166"
        ]


class TestAFailedLookupMustNotReadAsAnEmptyProject:
    """"I saw nothing" and "I could not look" are opposites: an unusable payload raises instead of
    yielding an empty set.
    """

    def test_a_payload_without_a_samples_key_raises(self):
        try:
            names_from_listing({"id": "644608203395018459", "name": "E-MTAB-2700"})
        except ValueError as exc:
            assert "samples" in str(exc).lower()
        else:
            raise AssertionError("a payload with no `samples` key must raise, not return set()")

    def test_none_raises(self):
        try:
            names_from_listing(None)
        except ValueError:
            pass
        else:
            raise AssertionError("a missing payload must raise")

    def test_an_explicitly_empty_sample_list_is_fine(self):
        """`{"samples": []}` is a real answer — the project is empty."""
        assert names_from_listing({"samples": []}) == set()


class TestATruncatedListingMustNotReadAsACleanImport:
    """A listing holding fewer samples than its `count` is provably incomplete, and refused.

    Story: FAILURES.md#listing-pagination
    """

    def test_a_short_envelope_raises(self):
        truncated = {"count": 24, "page": 1, "samples": [
            {"id": "1", "name": "APOBEC3G_CEMSS_Hs_T7_cell_rep1_ERR565167", "metadata": {}}]}
        try:
            names_from_listing(truncated)
        except ValueError as exc:
            assert "24" in str(exc) and "1" in str(exc)
        else:
            raise AssertionError("a truncated listing must not yield a name set")

    def test_a_complete_envelope_is_accepted(self):
        complete = {"count": 1, "page": 1, "samples": [
            {"id": "1", "name": "APOBEC3G_CEMSS_Hs_T7_cell_rep1_ERR565167", "metadata": {}}]}
        assert names_from_listing(complete) == {"APOBEC3G_CEMSS_Hs_T7_cell_rep1_ERR565167"}

    def test_a_countless_payload_still_works(self):
        """Hand-assembled listings carry no envelope; they are not provably short."""
        assert names_from_listing({"samples": [{"id": "1", "name": "x"}]}) == {"x"}

    def test_an_empty_project_is_not_mistaken_for_truncation(self):
        assert names_from_listing({"count": 0, "page": 1, "samples": []}) == set()
