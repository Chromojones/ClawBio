"""A completed import is not evidence the metadata arrived.

GSE252683 imported 12/12 samples, job ``COMPLETED``, every read attached. Six of the
sheet's eighteen columns had nevertheless been thrown away: `flowbio samples import`
accepts ``purification_target__annotation`` and ``source__annotation``, returns success,
and stores neither. All twelve samples lost ``nFLAG`` / ``Flp-In T-REx`` / ``neuroblastoma``
and no error was raised at any point.

That is the same silent-drop shape as the project field (fact 2 in
``reference/sra-direct-import.md``), and the fix is the same: read the samples back and
compare them to the sheet that produced them.

Two decoy failure modes are pinned here because both cost a debug cycle on the live data:

* the **project listing** endpoint returns trimmed samples with no ``metadata`` block, so
  verifying against it reports every field of every sample as missing;
* reads live under ``filesets[].data``, not a top-level ``data`` key, so the obvious
  ``len(sample["data"])`` reports 0 files for a fully populated sample.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_verify import (  # noqa: E402
    Discrepancy,
    find_import_discrepancies,
    format_report,
)

PROJECT = "606004733347380480"

SHEET_ROW = {
    "accession": "SRX23101348",
    "sample_type": "CLIP",
    "name": "HNRNPA1_HEK293_Hs_D262V_rep1_SRX23101348",
    "organism": "Homo sapiens",
    "purification_target": "HNRNPA1",
    "purification_target__annotation": "nFLAG",
    "purification_agent": "Anti-FLAG",
    "source": "HEK293",
    "source__annotation": "Flp-In T-REx",
    "condition": "D262V",
    "five_prime_barcode_sequence": "NNN",
}


def live_sample(**overrides) -> dict:
    """The shape of GET /samples/{id} — nested metadata, reads under `filesets`."""
    sample = {
        "id": "414565780120168206",
        "name": "HNRNPA1_HEK293_Hs_D262V_rep1_SRX23101348",
        "pubmed": "38182429",
        "project": {"id": PROJECT, "name": "hnRNPA1 ALS"},
        "metadata": {
            "purification_target": {"value": "HNRNPA1", "annotation": "nFLAG"},
            "purification_agent": {"value": "Anti-FLAG", "annotation": ""},
            "source": {"value": "HEK293", "annotation": "Flp-In T-REx"},
            "condition": {"value": "D262V", "annotation": ""},
            "five_prime_barcode_sequence": {"value": "NNN", "annotation": ""},
        },
        "filesets": [{"data": [{"filename": "SRX23101348_1.fastq.gz"},
                               {"filename": "SRX23101348_2.fastq.gz"}]}],
    }
    sample.update(overrides)
    return sample


class TestACleanImportIsSilent:
    def test_matching_sample_produces_nothing(self):
        found = find_import_discrepancies([SHEET_ROW], [live_sample()], project_id=PROJECT)
        assert found == []

    def test_columns_the_sheet_leaves_blank_are_not_checked(self):
        """A sparse sheet must not demand that Flow invent values."""
        row = dict(SHEET_ROW, condition="")
        live = live_sample()
        live["metadata"]["condition"] = {"value": "", "annotation": ""}
        assert find_import_discrepancies([row], [live], project_id=PROJECT) == []


class TestTheDroppedAnnotation:
    """The GSE252683 regression, verbatim."""

    def test_dropped_target_annotation_is_reported(self):
        live = live_sample()
        live["metadata"]["purification_target"]["annotation"] = ""
        found = find_import_discrepancies([SHEET_ROW], [live], project_id=PROJECT)
        assert [d.field for d in found] == ["purification_target__annotation"]
        assert found[0].expected == "nFLAG"
        assert found[0].actual == ""
        assert found[0].sample == SHEET_ROW["name"]

    def test_dropped_source_annotation_is_reported(self):
        live = live_sample()
        live["metadata"]["source"]["annotation"] = ""
        found = find_import_discrepancies([SHEET_ROW], [live], project_id=PROJECT)
        assert [d.field for d in found] == ["source__annotation"]

    def test_a_value_and_its_annotation_are_reported_separately(self):
        """They are distinct columns and one can survive while the other does not."""
        live = live_sample()
        live["metadata"]["source"] = {"value": "", "annotation": ""}
        fields = {d.field for d in find_import_discrepancies([SHEET_ROW], [live], project_id=PROJECT)}
        assert fields == {"source", "source__annotation"}


class TestTheDecoysThatCostADebugCycle:
    def test_a_trimmed_listing_sample_is_refused_not_reported_as_60_errors(self):
        """`/projects/{id}/samples` returns `metadata` as an EMPTY DICT, not as absent.

        Verbatim keys from the live endpoint. A first version of this guard tested
        `"metadata" not in sample` against a fabricated shape with the key removed — it
        passed the test and would have sailed straight past the real listing, producing
        exactly the 60 phantom discrepancies it was written to prevent. Presence of the key
        proves nothing; only a populated block does.

        Reporting this as "every field is missing" is worse than useless: it buries a real
        drop in noise and trains the reader to ignore the check.
        """
        trimmed = {
            "id": "414565780120168206", "name": SHEET_ROW["name"], "metadata": {},
            "sample_type": "CLIP", "private": True, "can_delete": True,
        }
        try:
            find_import_discrepancies([SHEET_ROW], [trimmed], project_id=PROJECT)
        except ValueError as exc:
            assert "metadata" in str(exc).lower()
        else:
            raise AssertionError("a trimmed listing sample must raise, not report 60 diffs")

    def test_reads_are_counted_under_filesets_not_a_top_level_data_key(self):
        assert find_import_discrepancies([SHEET_ROW], [live_sample()], project_id=PROJECT) == []

    def test_a_sample_with_no_reads_is_reported(self):
        found = find_import_discrepancies([SHEET_ROW], [live_sample(filesets=[])], project_id=PROJECT)
        assert [d.field for d in found] == ["reads"]
        assert "0" in found[0].actual


class TestAttachmentsThatAreNotSheetColumns:
    def test_unassigned_project_is_reported(self):
        live = live_sample(project=None)
        assert [d.field for d in find_import_discrepancies(
            [SHEET_ROW], [live], project_id=PROJECT)] == ["project"]

    def test_project_may_be_a_bare_id_rather_than_an_object(self):
        assert find_import_discrepancies(
            [SHEET_ROW], [live_sample(project=PROJECT)], project_id=PROJECT) == []

    def test_project_is_only_checked_when_the_caller_names_one(self):
        assert find_import_discrepancies([SHEET_ROW], [live_sample(project=None)]) == []

    def test_missing_pubmed_is_reported_when_expected(self):
        found = find_import_discrepancies(
            [SHEET_ROW], [live_sample(pubmed=None)], project_id=PROJECT, expect_pubmed="38182429")
        assert [d.field for d in found] == ["pubmed"]


class TestPairingSheetRowsToSamples:
    def test_a_sheet_row_with_no_imported_sample_is_reported(self):
        found = find_import_discrepancies([SHEET_ROW], [], project_id=PROJECT)
        assert [d.field for d in found] == ["sample"]
        assert "not imported" in found[0].detail.lower()

    def test_an_extra_sample_is_reported_rather_than_ignored(self):
        stray = live_sample(id="999", name="HNRNPA1_leftover_from_a_previous_attempt")
        found = find_import_discrepancies([SHEET_ROW], [live_sample(), stray], project_id=PROJECT)
        assert [d.field for d in found] == ["sample"]
        assert "not in the sheet" in found[0].detail.lower()


class TestTheReport:
    def test_a_clean_run_says_so_unambiguously(self):
        assert "0 discrepanc" in format_report([], total_rows=12).lower()

    def test_the_report_names_sample_field_expected_and_actual(self):
        text = format_report(
            [Discrepancy(sample="S1", field="source__annotation",
                         expected="Flp-In T-REx", actual="", detail="dropped by import")],
            total_rows=12,
        )
        for fragment in ("S1", "source__annotation", "Flp-In T-REx"):
            assert fragment in text
