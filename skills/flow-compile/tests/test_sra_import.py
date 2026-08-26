"""Tests for the SRA-direct import sheet (flowbio samples import).

Empirical constraints these tests lock in, discovered against the live API with
GSE215250 (PARP13 eCLIP):
  * the accession must be an SRX/ERX **experiment**; SRR run accessions return HTTP 500
  * `project` is reserved from flowbio 0.12.0 (see test_import_sheet_columns.py); below that
    version it was swallowed as metadata and the study landed unattached
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
    validate_import_sheet,
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


class TestCommentsLengthLimit:
    """Flow caps `comments` at 1000 characters; the import rejects the whole batch over it.

    GSE76475 hit this: an 11-row sheet was refused outright with

        validation_error … 7.metadata.comments … at most 1000 characters (it has 1025)

    One long row kills the entire import, and the message identifies the row only by
    position, so the sheet must be checked locally before the call. Comments are where this
    skill records the evidence for every judgement call, so they grow naturally — truncating
    silently would discard provenance, hence a loud error naming the offending samples.
    """

    def _sheet(self, comment: str) -> pd.DataFrame:
        return pd.DataFrame([{
            "accession": "SRX1122756", "sample_type": "CLIP", "name": "RBFOX1_Mm_Forebrain_HMW",
            "five_prime_barcode_sequence": "NNNNNNNNN", "purification_target": "RBFOX1",
            "comments": comment,
        }])

    def test_comment_at_the_limit_is_accepted(self):
        assert validate_import_sheet(self._sheet("x" * 1000)) is not None

    def test_comment_over_the_limit_raises_naming_the_sample(self):
        with pytest.raises(ValueError) as exc:
            validate_import_sheet(self._sheet("x" * 1001))
        assert "RBFOX1_Mm_Forebrain_HMW" in str(exc.value)
        assert "1001" in str(exc.value)

    def test_sheet_without_a_comments_column_is_unaffected(self):
        sheet = self._sheet("ok").drop(columns=["comments"])
        assert validate_import_sheet(sheet) is not None


class TestRunAccessionIsSilentlyExpanded:
    """An SRR is accepted by the import — and silently expanded to its parent experiment.

    The docstring long said run accessions "fail with HTTP 500". Re-tested 2026-08-12 against
    GSE78030 and that is no longer true, but the real behaviour is worse than an error:
    importing `SRR3175580` produced ONE sample carrying all four runs of SRX1590001 —

        SRX1590001_SRR3175580.fastq.gz   2.2 GB
        SRX1590001_SRR3175581.fastq.gz   2.8 GB
        SRX1590001_SRR3175582.fastq.gz   2.4 GB
        SRX1590001_SRR3175583.fastq.gz   2.6 GB

    A study whose replicates are separate runs of one experiment therefore cannot be imported
    per replicate: 26 SRRs would yield 26 samples each holding its whole experiment, ~250 GB
    of duplication, every sample mixing all four barcodes. The job reports COMPLETED, so
    nothing surfaces the problem downstream.

    The accession check stays, but the reason it gives must match reality — an operator who
    reads "HTTP 500" and sees a successful import will reasonably conclude the rule is stale.
    """

    def test_run_accession_is_still_rejected(self):
        assert not is_experiment_accession("SRR3175580")
        assert not is_experiment_accession("ERR102558")

    def test_experiment_accessions_are_accepted(self):
        for acc in ("SRX1590001", "ERX079997", "DRX000001"):
            assert is_experiment_accession(acc), acc

    def test_the_error_explains_the_silent_expansion_not_a_500(self):
        annotation = pd.DataFrame([{"Sample Name": "YTHDF1_rep1", "SRX": "SRR3175580"}])
        with pytest.raises(ValueError) as exc:
            build_import_sheet(annotation)
        message = str(exc.value)
        assert "SRR3175580" in message
        assert "500" not in message, "the HTTP 500 claim is stale and misleads"
        assert "experiment" in message.lower()
