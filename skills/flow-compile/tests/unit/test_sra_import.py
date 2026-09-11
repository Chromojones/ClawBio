"""The SRA-direct import sheet for `flowbio samples import`.

Verified against the live API with GSE215250 (PARP13 eCLIP): the accession is an SRX/ERX
experiment, since a run is silently expanded to its experiment; `project` and `pubmed` are
reserved from flowbio 0.12.0; `strandedness` is rejected for CLIP (422) although batch-template
lists it.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.sra_import import (  # noqa: E402
    FORBIDDEN_SHEET_COLUMNS,
    build_import_sheet,
    is_experiment_accession,
    validate_import_sheet,
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
        """`strandedness` is rejected for CLIP, and a direct-line sheet has no local reads."""
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


class TestCommentsLengthLimit:
    """Flow caps `comments` at 1000 characters, and one long row fails the whole import.

    The API names the row only by position (GSE76475: `7.metadata.comments … it has 1025`). Comments
    hold the evidence for judgement calls, so truncating would lose provenance: the error names the
    samples.
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
    """An SRR is accepted by the import and silently expanded to its parent experiment.

    Importing `SRR3175580` (GSE78030) produced one sample carrying all four runs of SRX1590001, with
    the job COMPLETED. The refusal gives that reason.

    Story: FAILURES.md#import-guards
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


class TestAnnotationSpellingIsNormalisedOnTheWayOut:
    """The validator accepts `noUV` in any case; Flow must receive the one spelling."""

    def test_the_import_sheet_carries_the_canonical_no_uv(self):
        from lib.sra_import import annotation_to_flow_row

        row = annotation_to_flow_row({"Sample Name": "TARDBP_Hs_HeLa_noUV_rep1",
                                      "Protein (Purification Target)": "TARDBP",
                                      "Purification Target Annotation": "nouv"})
        assert row["purification_target__annotation"] == "noUV"
