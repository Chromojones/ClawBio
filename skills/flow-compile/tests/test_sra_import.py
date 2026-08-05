"""Tests for the SRA-direct import sheet (flowbio samples import).

Empirical constraints these tests lock in, discovered against the live API with
GSE215250 (PARP13 eCLIP):
  * the accession must be an SRX/ERX **experiment**; SRR run accessions return HTTP 500
  * the sheet has no `project` column — project assignment is a separate step
  * `strandedness` is rejected for CLIP (422) even though batch-template lists it
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.sra_import import (  # noqa: E402
    FORBIDDEN_SHEET_COLUMNS,
    build_import_sheet,
    is_experiment_accession,
    write_import_scripts,
    write_import_sheet,
)


def _annotation():
    return pd.DataFrame(
        [
            {
                "Sample Name": "PARP13_HEK293T_Hs_basal_rep1",
                "Experimental Method": "eCLIP",
                "Purification Agent": "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)",
                "Protein (Purification Target)": "PARP13",
                "Purification Target Annotation": "",
                "Cell or Tissue": "HEK293T",
                "Organism": "Hs",
                "Condition": "basal",
                "Sequencer": "Illumina HiSeq 4000",
                "5' Barcode Sequence": "NNNNNNNNNN",
                "GEO ID": "GSM6630369",
                "Scientist": "Vinay F. Busa",
                "PI": "Anthony K. L. Leung",
                "SRX": "SRX17851507",
            },
            {
                "Sample Name": "SMInput_HEK293T_Hs_basal_rep1",
                "Experimental Method": "eCLIP",
                "Purification Agent": "no antibody",
                "Protein (Purification Target)": "SMInput",
                "Purification Target Annotation": "",
                "Cell or Tissue": "HEK293T",
                "Organism": "Hs",
                "Condition": "basal",
                "Sequencer": "Illumina HiSeq 4000",
                "5' Barcode Sequence": "NNNNNNNNNN",
                "GEO ID": "GSM6630370",
                "Scientist": "Vinay F. Busa",
                "PI": "Anthony K. L. Leung",
                "SRX": "SRX17851508",
            },
        ]
    )


class TestAccessionKind:
    @pytest.mark.parametrize("acc", ["SRX17851507", "ERX123456", "DRX999"])
    def test_experiment_accessions_accepted(self, acc):
        assert is_experiment_accession(acc)

    @pytest.mark.parametrize("acc", ["SRR21863801", "ERR039788", "GSM6630369", ""])
    def test_run_and_other_accessions_rejected(self, acc):
        assert not is_experiment_accession(acc)


class TestBuildImportSheet:
    def test_required_columns_present(self):
        sheet = build_import_sheet(_annotation())
        for col in ("accession", "sample_type", "name", "five_prime_barcode_sequence",
                    "purification_target"):
            assert col in sheet.columns

    def test_uses_experiment_accession(self):
        sheet = build_import_sheet(_annotation())
        assert list(sheet["accession"]) == ["SRX17851507", "SRX17851508"]

    def test_forbidden_columns_never_emitted(self):
        """`project` is not a sheet field; `strandedness` is rejected for CLIP."""
        sheet = build_import_sheet(_annotation())
        for col in FORBIDDEN_SHEET_COLUMNS:
            assert col not in sheet.columns

    def test_metadata_is_carried_across(self):
        sheet = build_import_sheet(_annotation())
        row = sheet.iloc[0]
        assert row["purification_agent"] == "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)"
        assert row["source"] == "HEK293T"
        assert row["organism"] == "Hs"
        assert row["experimental_method"] == "eCLIP"
        assert row["geo"] == "GSM6630369"

    def test_control_row_keeps_its_own_target(self):
        sheet = build_import_sheet(_annotation())
        assert sheet.iloc[1]["purification_target"] == "SMInput"
        assert sheet.iloc[1]["purification_agent"] == "no antibody"

    def test_missing_srx_raises(self):
        df = _annotation()
        df.loc[0, "SRX"] = ""
        with pytest.raises(ValueError, match="experiment accession"):
            build_import_sheet(df)

    def test_run_accession_in_srx_column_raises(self):
        df = _annotation()
        df.loc[0, "SRX"] = "SRR21863801"
        with pytest.raises(ValueError, match="experiment accession"):
            build_import_sheet(df)

    def test_empty_optional_metadata_is_dropped_not_blank(self):
        """A tag annotation that is legitimately empty must not become an empty column value."""
        sheet = build_import_sheet(_annotation())
        assert "purification_target__annotation" not in sheet.columns


class TestWriteArtifacts:
    def test_sheet_written_as_csv(self, tmp_path):
        path = write_import_sheet(tmp_path, build_import_sheet(_annotation()))
        assert path.name == "import_sheet.csv"
        text = path.read_text(encoding="utf-8")
        assert "SRX17851507" in text
        assert "strandedness" not in text

    def test_scripts_reference_sheet_and_project(self, tmp_path):
        sheet = write_import_sheet(tmp_path, build_import_sheet(_annotation()))
        script = write_import_scripts(tmp_path, sheet_path=sheet, project_id="550540342405942387")
        body = script.read_text(encoding="utf-8")
        assert "samples import --sheet" in body
        assert "import-status" in body
        assert "550540342405942387" in body
        assert script.name == "sra_import.sh"
