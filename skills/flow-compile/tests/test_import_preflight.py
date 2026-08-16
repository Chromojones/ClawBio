"""Ask the project what it holds before importing. A status note is not evidence.

E-MTAB-2700's `ANALYSIS_STATUS.md` said **BLOCKED — everything ready, EBI file server down**,
and stated plainly that both jobs had reported `sample_ids: []` so "a retry cannot duplicate".

That was true when written. Two days later the original imports had in fact completed —
`watch_import.log` recorded `cell: COMPLETED, 12 samples` / `virion: COMPLETED, 12 samples` —
and nobody updated the note. Re-running the import on the strength of the note produced **48
samples in a 24-sample project**, every one duplicated, which then had to be untangled by
creation date and deleted.

The note was my own writing, which is exactly why it was believed. The project itself was one
request away and could not have been stale.

Note which endpoint this needs: the **trimmed** listing from `GET /projects/{id}/samples` is
the right one here, because a pre-flight only needs names. That same trimmed shape is useless
for `import_verify`, which needs metadata — see `test_import_verify.py`.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_preflight import (  # noqa: E402
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
    """The dangerous direction: "I saw nothing" and "I could not look" are opposites here.

    A failed lookup silently returning zero already produced one no-op upload that reported
    success, so an unusable payload raises instead of yielding an empty set.
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
