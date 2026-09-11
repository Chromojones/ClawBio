"""The import round trip, and one definition of the columns that are not metadata.

The reserved set is `sra_import.RESERVED_SHEET_COLUMNS`, asserted equal to flowbio's constant.
`project` is reserved and delivered at the top level, so it is never reported as dropped metadata.

Story: FAILURES.md#import-check
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import import_check  # noqa: E402
from lib.import_check import (  # noqa: E402
    build_repair_plan,
    find_already_present,
    find_import_discrepancies,
    live_metadata,
    names_from_listing,
)

SHEET_ROW = {
    "accession": "SRX1", "sample_type": "CLIP", "name": "S1", "project": "P1",
    "purification_target": "LARP6", "purification_target__annotation": "dCTR-nMYC",
}


def _live(**over):
    sample = {
        "name": "S1", "id": "9", "project": {"id": "P1"},
        "metadata": {
            "purification_target": {"value": "LARP6", "annotation": "dCTR-nMYC"},
        },
        "filesets": [{"data": [{"id": "1"}]}],
    }
    sample.update(over)
    return sample


class TestReservedColumnsAreNotMetadata:
    """A reserved column is not looked for under `metadata`."""

    def test_one_definition_shared_by_both_phases(self):
        from lib.sra_import import RESERVED_SHEET_COLUMNS

        assert set(import_check.NON_METADATA_COLUMNS) == set(RESERVED_SHEET_COLUMNS)

    def test_project_is_not_reported_as_dropped(self):
        """It is delivered at the top level, not inside metadata."""
        found = find_import_discrepancies([SHEET_ROW], [_live()], project_id="P1")
        assert [d for d in found if d.field == "project"] == []

    def test_project_does_not_generate_a_pointless_repair(self):
        plan = build_repair_plan([SHEET_ROW], [_live()], project_id="P1")
        assert [e for e in plan if "project" in e.fields] == []

    def test_pubmed_is_reserved_too(self):
        row = dict(SHEET_ROW, pubmed="31216479")
        found = find_import_discrepancies([row], [_live()], project_id="P1")
        assert [d for d in found if d.field == "pubmed"] == []

    def test_a_genuinely_wrong_project_is_still_caught(self):
        """Reserved must not mean unchecked."""
        found = find_import_discrepancies(
            [SHEET_ROW], [_live(project={"id": "WRONG"})], project_id="P1")
        assert [d.field for d in found if d.field == "project"] == ["project"]


class TestTheRealFindingStillSurfaces:
    def test_a_dropped_annotation_is_reported(self):
        """The reason the verify stage exists: the import job discards __annotation."""
        live = _live(metadata={"purification_target": {"value": "LARP6", "annotation": ""}})
        found = find_import_discrepancies([SHEET_ROW], [live], project_id="P1")
        assert "purification_target__annotation" in [d.field for d in found]

    def test_a_dropped_annotation_is_repaired(self):
        live = _live(metadata={"purification_target": {"value": "LARP6", "annotation": ""}})
        plan = build_repair_plan([SHEET_ROW], [live], project_id="P1")
        assert plan[0].fields["purification_target__annotation"] == "dCTR-nMYC"

    def test_a_sample_with_no_reads_is_reported(self):
        found = find_import_discrepancies([SHEET_ROW], [_live(filesets=[])], project_id="P1")
        assert any("read" in d.detail.lower() or d.field == "reads" for d in found)


class TestPreflightStillWorks:
    def test_names_from_listing(self):
        assert names_from_listing({"samples": [{"name": "S1"}, {"name": "S2"}]}) == {"S1", "S2"}

    def test_already_present_is_found(self):
        assert find_already_present([SHEET_ROW], {"S1"}) == ["S1"]

    def test_a_clean_import_reports_none(self):
        assert find_already_present([SHEET_ROW], {"other"}) == []


class TestAnnotationReadback:
    def test_annotation_is_read_from_the_nested_block(self):
        assert live_metadata(_live(), "purification_target__annotation") == "dCTR-nMYC"

    def test_value_is_read_from_the_nested_block(self):
        assert live_metadata(_live(), "purification_target") == "LARP6"

    def test_a_missing_attribute_is_empty_not_an_error(self):
        assert live_metadata(_live(), "source") == ""


class TestVerificationRefusesAProvablyShortListing:
    """A listing shorter than its envelope's `count` is refused, not reported as missing samples.

    Story: FAILURES.md#listing-pagination
    """

    def test_an_envelope_shorter_than_its_count_raises(self):
        rows = [{"name": "S1"}, {"name": "S2"}]
        envelope = {"count": 2, "samples": [{"name": "S1", "metadata": {"x": {"value": "1"}}}]}
        try:
            find_import_discrepancies(rows, envelope)
        except ValueError as exc:
            assert "2" in str(exc) and "1" in str(exc)
        else:
            raise AssertionError("a provably short listing must not be verified against")

    def test_a_complete_envelope_is_unwrapped_and_verified(self):
        rows = [{"name": "S1"}]
        envelope = {"count": 1, "samples": [{"name": "S1", "metadata": {"x": {"value": "1"}}}]}
        assert find_import_discrepancies(rows, envelope, expect_reads=False) == []

    def test_a_plain_list_still_works(self):
        rows = [{"name": "S1"}]
        live = [{"name": "S1", "metadata": {"x": {"value": "1"}}}]
        assert find_import_discrepancies(rows, live, expect_reads=False) == []
