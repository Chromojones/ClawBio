"""Organism is Flow's two-letter code, never the Latin or common name.

The API rejects anything else with `Does not exist.`, after the reads are staged (GSE159997:
`Mus musculus`, 18 rows). Codes are the live set from `GET /api/organisms`; unknown codes are
refused.
"""

import sys

import pytest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import ERROR, validate_organism  # noqa: E402


class TestTheAcceptedCodes:
    def test_human_and_mouse_pass(self):
        assert validate_organism("Hs") == []
        assert validate_organism("Mm") == []

    def test_every_live_code_passes(self):
        """Verbatim from GET /api/organisms."""
        for code in ("Hs", "Mm", "Rn", "Dr", "Dm", "Sc", "Ec", "Gg", "At", "Vf"):
            assert validate_organism(code) == [], code

    def test_surrounding_whitespace_is_tolerated(self):
        assert validate_organism("  Mm ") == []


class TestTheGse159997Regression:
    def test_the_latin_name_is_refused(self):
        checks = validate_organism("Mus musculus")
        assert [c.severity for c in checks] == [ERROR]

    def test_the_message_gives_the_code_to_use_rather_than_just_saying_no(self):
        message = validate_organism("Mus musculus")[0].message
        assert "Mm" in message

    def test_the_human_latin_name_is_refused_too(self):
        assert validate_organism("Homo sapiens")[0].message.count("Hs") >= 1

    def test_the_common_name_is_refused(self):
        """`Mouse` is what the API *displays*, which makes it an easy wrong answer."""
        assert validate_organism("Mouse")[0].severity == ERROR
        assert "Mm" in validate_organism("Mouse")[0].message


class TestOtherWrongShapes:
    def test_an_empty_organism_is_an_error(self):
        assert validate_organism("")[0].severity == ERROR

    def test_an_unknown_code_is_refused(self):
        checks = validate_organism("Xx")
        assert checks and checks[0].severity == ERROR

    def test_case_matters_because_the_api_is_case_sensitive(self):
        """`mm` is not `Mm`; accepting it here would just move the failure downstream."""
        assert validate_organism("mm")[0].severity == ERROR

    def test_a_taxid_is_refused(self):
        assert validate_organism("10090")[0].severity == ERROR


class TestWiredIntoTheGate:
    def test_the_table_validator_reports_a_bad_organism(self):
        import pandas as pd

        from lib.metadata_validate import validate_annotation_table

        table = pd.DataFrame([{
            "Sample Name": "CSDE1_PMK_Mm_EV_rep1_SRX9351670",
            "Protein (Purification Target)": "CSDE1",
            "Purification Target Annotation": "",
            "Purification Agent": "Anti-CSDE1",
            "Cell or Tissue": "Keratinocyte",
            "Condition": "empty vector",
            "5' Barcode Sequence": "NNNNCCGGANNN",
            "Organism": "Mus musculus",
        }])
        issues = validate_annotation_table(table)
        assert any(i.field == "Organism" and i.severity == ERROR for i in issues)

    def test_a_table_without_an_organism_column_is_not_forced_to_have_one(self):
        """Sheets built for the edit path legitimately omit it."""
        import pandas as pd

        from lib.metadata_validate import validate_annotation_table

        table = pd.DataFrame([{
            "Sample Name": "x",
            "Protein (Purification Target)": "CSDE1",
            "Purification Target Annotation": "",
            "Purification Agent": "Anti-CSDE1",
            "Cell or Tissue": "Keratinocyte",
            "Condition": "empty vector",
            "5' Barcode Sequence": "NNNNCCGGANNN",
        }])
        assert not any(i.field == "Organism" for i in validate_annotation_table(table))


class TestOneOrganismTable:
    """`lib/organism.py` and the validator share one table of Flow's ten codes."""

    def test_the_validator_and_the_normaliser_share_one_table(self):
        from lib import metadata_validate, organism

        assert metadata_validate.ORGANISM_CODES is organism.ORGANISM_CODES

    @pytest.mark.parametrize("raw,code", [
        ("Drosophila melanogaster", "Dm"), ("Dm", "Dm"), ("Danio rerio", "Dr"),
        ("Rattus norvegicus", "Rn"), ("Homo sapiens", "Hs"), ("mouse", "Mm"),
    ])
    def test_every_flow_organism_normalises(self, raw, code):
        from lib.organism import normalize_organism

        assert normalize_organism(raw) == code

    def test_the_column_check_accepts_every_code(self):
        from lib.organism import ORGANISM_CODES, validate_organism_column

        assert validate_organism_column(list(ORGANISM_CODES)) == []
