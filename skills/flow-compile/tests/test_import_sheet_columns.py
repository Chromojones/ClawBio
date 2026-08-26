"""What the accession sheet may carry, checked against flowbio's own constant.

`project` was on the forbidden list with the reason "the import API has no project field —
assign after import". That was true of flowbio 0.10.0, whose `RESERVED_COLUMNS` really was
`(accession, name, organism, sample_type)`. Every imported study therefore landed unattached
and needed a second pass with `flow_project_assign.py`, and the claim was written into the
skill in five places.

flowbio 0.12.0 reserves `("accession", "name", "organism", "project", "pubmed", "sample_type")`
and `AccessionSheetRow.to_spec()` maps them to `project_id` and `pubmed`. The post-import
assignment step is no longer required for a fresh import; it stays as a repair for the studies
imported before this.

These tests read flowbio's constant rather than restating it, so a downgrade or an upstream
change fails here instead of silently unattaching a study.

Two things that did NOT change, both verified against the live API:

* **The import job still drops `__annotation` columns.** The CLI forwards them as ordinary
  metadata keys — `_build_row` puts every non-reserved column into `metadata` — so the loss is
  server-side, in the import job rather than the client. `POST /samples/{id}/edit` accepts the
  same flat `purification_target__annotation` key and honours it, which is why the post-import
  edit pass works.
* **A colon in a value is not an annotation separator.** Flow's UI *renders* an annotated
  attribute as `value:annotation`, but that is display only. Setting `source` to
  `"U87:TESTANNOT"` on sample 499341935928905194 stored the colon literally
  (`value='U87:TESTANNOT'`, `annotation='Glioblastoma'` unchanged). The server's model keeps
  `annotation` as its own field.

Story: FAILURES.md#import-sheet-columns
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.sra_import import (  # noqa: E402
    FORBIDDEN_SHEET_COLUMNS,
    MIN_FLOWBIO_VERSION,
    RESERVED_SHEET_COLUMNS,
)


class TestAgainstFlowbioItself:
    """Read the library's constant, do not restate it."""

    def test_our_reserved_set_matches_the_installed_flowbio(self):
        sheet = pytest.importorskip("flowbio.cli._accession_sheet")
        assert set(RESERVED_SHEET_COLUMNS) == set(sheet.RESERVED_COLUMNS)

    def test_project_is_reserved_upstream(self):
        sheet = pytest.importorskip("flowbio.cli._accession_sheet")
        assert "project" in sheet.RESERVED_COLUMNS

    def test_the_spec_actually_carries_project_and_pubmed(self):
        """A reserved column that never reaches the API would be worse than a forbidden one."""
        mod = pytest.importorskip("flowbio.cli._accession_sheet")
        row = mod.AccessionSheetRow(
            row_number=1, accession="SRX1", name="S1", organism="9606",
            project="P1", pubmed=None, sample_type="CLIP", metadata={},
        )
        spec = row.to_spec()
        assert spec.project_id == "P1"

    def test_installed_flowbio_meets_our_minimum(self):
        """`flowbio` exposes no __version__, so ask the installed distribution."""
        from importlib.metadata import PackageNotFoundError, version

        try:
            installed = tuple(int(p) for p in version("flowbio").split(".")[:3])
        except PackageNotFoundError:
            pytest.skip("flowbio not installed")
        assert installed >= MIN_FLOWBIO_VERSION


class TestProjectIsNoLongerForbidden:
    def test_project_is_not_on_the_forbidden_list(self):
        assert "project" not in FORBIDDEN_SHEET_COLUMNS

    def test_a_sheet_may_carry_a_project(self):
        import pandas as pd

        from lib.sra_import import build_import_sheet

        sheet = build_import_sheet(
            pd.DataFrame([{
                "Sample Name": "S1", "SRX": "SRX111", "Organism": "9606",
                "Protein (Purification Target)": "LARP6",
                "5' Barcode Sequence": "NNNGGCGNN",
            }]),
            project_id="P1",
        )
        assert sheet.loc[0, "project"] == "P1"

    def test_no_project_column_when_none_is_given(self):
        """An empty project column would be sent as an empty string, not omitted."""
        import pandas as pd

        from lib.sra_import import build_import_sheet

        sheet = build_import_sheet(pd.DataFrame([{
            "Sample Name": "S1", "SRX": "SRX111",
            "Protein (Purification Target)": "LARP6",
            "5' Barcode Sequence": "NNNGGCGNN",
        }]))
        assert "project" not in sheet.columns


class TestStillForbidden:
    def test_strandedness_is_still_refused(self):
        """The CLIP template lists it required; the CLIP endpoint rejects it. Unchanged in 0.12.0."""
        assert "strandedness" in FORBIDDEN_SHEET_COLUMNS

    def test_reads_columns_are_still_refused(self):
        assert "reads1" in FORBIDDEN_SHEET_COLUMNS
        assert "reads2" in FORBIDDEN_SHEET_COLUMNS


class TestAnnotationSurvivesTheSheetButNotTheJob:
    def test_annotation_columns_are_still_written(self):
        """Dropping them locally would remove the record; the post-import edit pass reads it."""
        import pandas as pd

        from lib.sra_import import build_import_sheet

        sheet = build_import_sheet(pd.DataFrame([{
            "Sample Name": "S1", "SRX": "SRX111",
            "Protein (Purification Target)": "LARP6",
            "Purification Target Annotation": "dCTR-nMYC",
            "5' Barcode Sequence": "NNNGGCGNN",
        }]))
        assert sheet.loc[0, "purification_target__annotation"] == "dCTR-nMYC"

    def test_a_colon_is_not_an_annotation_separator(self):
        """Verified live: the colon is stored in the value, the annotation is untouched.

        Flow's UI renders `value:annotation`, which is display only. Encoding an annotation
        that way would write a literal colon into the target name.
        """
        from lib.sra_import import annotation_is_transportable_in_value

        assert annotation_is_transportable_in_value() is False
