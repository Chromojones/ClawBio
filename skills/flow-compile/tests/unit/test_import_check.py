"""One module for the import round trip, and one definition of "not a metadata column".

`import_preflight` (is this name already on Flow?), `import_verify` (did the import deliver
what the sheet said?) and `import_repair` (fix what it didn't) are three phases of one
question, and they shared two copies of the same constant under two names:

    import_verify.py:40   _NON_METADATA_COLUMNS = frozenset({"accession", "sample_type", "name", "organism"})
    import_repair.py:32   _NON_METADATA         = frozenset({"accession", "sample_type", "name", "organism"})

Both were correct for flowbio 0.10.0 and both went stale the moment `project` became a
reserved import-sheet column in 0.12.0. With a `project` column in the sheet, a column that is
*reserved* gets treated as *metadata*: `live_metadata()` looks for `metadata["project"]`, finds
nothing (the API returns project at the top level), and every sample in the study is reported
as `project dropped by the import` while the repair plan queues a pointless edit re-setting a
project that is already right.

That is the 41-false-warnings shape again — a wall of findings burying the real ones — and it
arrived the same afternoon the reserved set changed, in two places at once, which is the
argument for the merge.

The reserved set now has one definition, in `sra_import.RESERVED_SHEET_COLUMNS`, which is
itself asserted equal to flowbio's own constant.

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
    """The regression the merge exists to prevent."""

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


class TestOldImportPathsStillWork:
    """Phase 2 leaves re-export shims; they go in the final commit."""

    def test_import_verify_shim(self):
        from lib.import_check import find_import_discrepancies as shim

        assert shim is find_import_discrepancies

    def test_import_repair_shim(self):
        from lib.import_check import build_repair_plan as shim

        assert shim is build_repair_plan

    def test_import_preflight_shim(self):
        from lib.import_check import find_already_present as shim

        assert shim is find_already_present
