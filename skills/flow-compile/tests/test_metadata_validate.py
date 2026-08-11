"""Tests for metadata accuracy guardrails (antibody, source, target/tag, 5' barcode).

Regression fixtures come from two real studies that broke the naive scrape:
  * GSE215250 (PARP13 eCLIP, PMID 38495826) — two candidate antibodies in Key Resources,
    GEO says HEK293 but the line is HEK293T, and SMInput rows must not carry the IP target.
  * GSE105082 (demo)              — !Sample_source_name_ch1 is "ATCC Cell Lines", a supplier
    phrase, while the real line is HeLa.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import (  # noqa: E402
    ERROR,
    WARNING,
    normalize_purification_agent,
    validate_annotation_table,
    validate_five_prime_barcode,
    validate_purification_agent,
    validate_source,
    validate_target_and_annotation,
    write_metadata_hook,
)


class TestPurificationAgentNormalization:
    """The model may type the antibody any number of ways; code canonicalizes it."""

    @pytest.mark.parametrize(
        "raw",
        [
            "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)",
            "Rabbit anti-PARP13 (Thermo Fisher PA5-31650)",
            "rabbit anti-PARP13 (Thermo Fisher, PA5-31650)",
            "Rabbit anti-PARP13 (Thermo Fisher, cat# PA5-31650)",
            "  Rabbit   anti-PARP13  ( Thermo Fisher , PA5-31650 )  ",
        ],
    )
    def test_variants_collapse_to_one_canonical_string(self, raw):
        assert normalize_purification_agent(raw) == "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)"

    def test_allowed_literals_pass_through(self):
        assert normalize_purification_agent("no antibody") == "no antibody"
        assert normalize_purification_agent("No Antibody") == "no antibody"

    @pytest.mark.parametrize(
        "raw", ["PARP13 antibody", "V5-antibody", "anti-PARP13 antibody", "", "   "]
    )
    def test_unparseable_returns_empty(self, raw):
        assert normalize_purification_agent(raw) == ""

    @pytest.mark.parametrize(
        "raw",
        [
            "Rabbit Anti-PARP13 (Santa Cruz, 1:500)",
            "Rabbit Anti-PARP13 (Santa Cruz, 1:1,000)",
            "Rabbit Anti-PARP13 (Santa Cruz, dilution)",
        ],
    )
    def test_dilution_is_not_a_catalog_number(self, raw):
        """A Methods sentence often gives the dilution, not the catalog — reject it."""
        assert normalize_purification_agent(raw) == ""


class TestPurificationAgentValidation:
    def test_canonical_agent_is_accepted(self):
        assert validate_purification_agent(
            "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)", target="PARP13"
        ) == []

    def test_vendorless_agent_is_an_error(self):
        issues = validate_purification_agent("PARP13 antibody", target="PARP13")
        assert issues and issues[0][0] == ERROR

    def test_v5_antibody_is_an_error(self):
        """The skill itself synthesizes this string; it carries no vendor or catalog."""
        issues = validate_purification_agent("V5-antibody", target="MBNL2")
        assert issues and issues[0][0] == ERROR

    def test_empty_agent_is_an_error(self):
        issues = validate_purification_agent("", target="PARP13")
        assert issues and issues[0][0] == ERROR

    def test_control_target_requires_no_antibody(self):
        # Convention: controls carry an EMPTY agent. `no antibody` is tolerated as legacy
        # input but warned, so existing rows are not hard-failed.
        assert validate_purification_agent("", target="SMInput") == []
        assert validate_purification_agent("", target="IgG") == []

    def test_control_with_legacy_no_antibody_warns_not_errors(self):
        checks = validate_purification_agent("no antibody", target="SMInput")
        assert checks, "legacy literal should be surfaced"
        assert all(c.severity != ERROR for c in checks)

    def test_control_carrying_a_real_antibody_is_an_error(self):
        issues = validate_purification_agent(
            "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)", target="SMInput"
        )
        assert issues and issues[0][0] == ERROR

    def test_agent_target_mismatch_is_flagged(self):
        """Antibody names a different protein than the row's purification target."""
        issues = validate_purification_agent(
            "Rabbit Anti-TRIM25 (Thermo Fisher PA5-31650)", target="PARP13"
        )
        assert issues and any(check.severity == WARNING for check in issues)


class TestSourceValidation:
    @pytest.mark.parametrize("value", ["HEK293T", "HeLa", "K562", "mESC"])
    def test_specific_cell_lines_pass(self, value):
        assert validate_source(value) == []

    def test_supplier_phrase_is_an_error(self):
        """GSE105082 !Sample_source_name_ch1 == 'ATCC Cell Lines'."""
        issues = validate_source("ATCC Cell Lines")
        assert issues and issues[0][0] == ERROR

    def test_generic_tissue_descriptor_is_an_error(self):
        """GSE215250 GEO source_name == 'human embryonic kidney'."""
        issues = validate_source("human embryonic kidney")
        assert issues and issues[0][0] == ERROR

    def test_empty_source_is_an_error(self):
        issues = validate_source("")
        assert issues and issues[0][0] == ERROR

    def test_ambiguous_line_warns_but_does_not_auto_fix(self):
        """HEK293 vs HEK293T must be confirmed against the paper, never silently rewritten."""
        issues = validate_source("HEK293")
        assert issues and issues[0][0] == WARNING
        assert "HEK293T" in issues[0][1]


class TestTargetAndAnnotation:
    def test_endogenous_ip_has_empty_annotation(self):
        assert validate_target_and_annotation(
            target="PARP13", annotation="", agent="Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)"
        ) == []

    @pytest.mark.parametrize(
        "tag", ["c3xFLAG-HBH", "cV5", "cGFP", "nFLAG", "cHA", "nMYC", "cHBH"]
    )
    def test_valid_tag_grammar(self, tag):
        assert validate_target_and_annotation(target="QKI", annotation=tag, agent="") == []

    @pytest.mark.parametrize("tag", ["GFP", "3xFLAG", "C-3xFLAG", "c-3xFLAG", "flag", "cBANANA"])
    def test_invalid_tag_grammar_is_an_error(self, tag):
        issues = validate_target_and_annotation(target="QKI", annotation=tag, agent="")
        assert issues and issues[0][0] == ERROR

    def test_control_row_must_not_carry_ip_target(self):
        issues = validate_target_and_annotation(
            target="PARP13", annotation="", agent="no antibody", sample_name="SMInput_HEK293T_Hs_rep1"
        )
        assert issues and issues[0][0] == ERROR
        assert "SMInput" in issues[0][1]

    def test_control_row_with_control_target_is_fine(self):
        assert validate_target_and_annotation(
            target="SMInput", annotation="", agent="no antibody",
            sample_name="SMInput_HEK293T_Hs_rep1",
        ) == []

    def test_non_gene_target_is_an_error(self):
        """infer_protein_target's fallback can emit ANTI-FLAG / RABBIT."""
        for bad in ("ANTI-FLAG", "RABBIT"):
            issues = validate_target_and_annotation(target=bad, annotation="", agent="")
            assert issues and issues[0][0] == ERROR


class TestFivePrimeBarcode:
    @pytest.mark.parametrize("bc", ["NNNNNNNNNN", "NNNCAATNN", "ACGT", "NNCCNNACC"])
    def test_acgtn_strings_pass(self, bc):
        assert validate_five_prime_barcode(bc) == []

    @pytest.mark.parametrize("bc", ["", "NNNXNNN", "NNN-NNN", "10N"])
    def test_non_acgtn_is_an_error(self, bc):
        issues = validate_five_prime_barcode(bc)
        assert issues and issues[0][0] == ERROR

    def test_length_mismatch_against_umi_header_format_warns(self):
        issues = validate_five_prime_barcode("NNNCAATNN", umi_header_format="NNNNNNNNNN")
        assert issues and issues[0][0] == WARNING

    def test_matching_length_is_clean(self):
        assert validate_five_prime_barcode("NNNCAATNN", umi_header_format="NNNNNNNNN") == []


class TestAnnotationTableValidation:
    def _parp13_rows(self):
        return pd.DataFrame(
            [
                {
                    "Sample Name": "PARP13_HEK293T_Hs_basal_rep1",
                    "Purification Agent": "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)",
                    "Cell or Tissue": "HEK293T",
                    "Protein (Purification Target)": "PARP13",
                    "Purification Target Annotation": "",
                    "5' Barcode Sequence": "NNNNNNNNNN",
                },
                {
                    "Sample Name": "SMInput_HEK293T_Hs_basal_rep1",
                    # Convention: controls carry an empty agent, not "no antibody".
                    "Purification Agent": "",
                    "Cell or Tissue": "HEK293T",
                    "Protein (Purification Target)": "SMInput",
                    "Purification Target Annotation": "",
                    "5' Barcode Sequence": "NNNNNNNNNN",
                },
            ]
        )

    def test_correct_parp13_table_is_clean(self):
        assert validate_annotation_table(self._parp13_rows()) == []

    def test_wrong_antibody_and_source_are_caught(self):
        df = self._parp13_rows()
        # the Western-blot antibody, and the GEO cell line
        df.loc[0, "Purification Agent"] = "PARP13 antibody"
        df.loc[0, "Cell or Tissue"] = "human embryonic kidney"
        issues = validate_annotation_table(df)
        fields = {i.field for i in issues}
        assert "Purification Agent" in fields
        assert "Cell or Tissue" in fields
        assert all(i.row == 2 for i in issues)  # 1-based + header

    def test_input_row_carrying_ip_target_is_caught(self):
        df = self._parp13_rows()
        df.loc[1, "Protein (Purification Target)"] = "PARP13"
        issues = validate_annotation_table(df)
        assert any(i.field == "Protein (Purification Target)" for i in issues)


class TestMetadataHook:
    def test_hook_writes_confirm_file_and_json(self, tmp_path):
        df = pd.DataFrame(
            [
                {
                    "Sample Name": "X_rep1",
                    "Purification Agent": "PARP13 antibody",
                    "Cell or Tissue": "ATCC Cell Lines",
                    "Protein (Purification Target)": "PARP13",
                    "Purification Target Annotation": "",
                    "5' Barcode Sequence": "NNNNNNNNNN",
                }
            ]
        )
        issues = validate_annotation_table(df)
        path = write_metadata_hook(tmp_path, issues)
        assert path.name == "CONFIRM_METADATA.md"
        assert (tmp_path / "metadata_validation.json").exists()
        text = path.read_text(encoding="utf-8")
        assert "Purification Agent" in text and "Cell or Tissue" in text

    def test_clean_table_reports_no_issues(self, tmp_path):
        path = write_metadata_hook(tmp_path, [])
        assert "No metadata issues" in path.read_text(encoding="utf-8")


class TestAbControl:
    """`AbControl` — an antibody pulldown on cells lacking the target.

    Distinct from SMInput: the antibody *was* used, so the agent must be kept, not blanked.
    GSE297587's `U87 Control` rows are a myc IP on untransfected cells.
    """

    def test_abcontrol_keeps_its_antibody(self):
        assert validate_purification_agent(
            "Mouse Anti-Myc (Abcam ab32)", target="AbControl"
        ) == []

    def test_abcontrol_with_empty_agent_is_flagged(self):
        """Unlike SMInput, an antibody control without an antibody is incoherent."""
        issues = validate_purification_agent("", target="AbControl")
        assert issues and issues[0][0] == ERROR

    def test_sminput_still_requires_empty_agent(self):
        assert validate_purification_agent("", target="SMInput") == []

    def test_abcontrol_row_is_not_treated_as_the_ip_protein(self):
        assert validate_target_and_annotation(
            target="AbControl", annotation="", agent="Mouse Anti-Myc (Abcam ab32)",
            sample_name="AbControl_U87_Hs_Rep1",
        ) == []


class TestTaggedPulldownAgreement:
    """A tag pulldown's antibody names the TAG, not the protein — that is not a mismatch.

    `Mouse Anti-Myc (Cell Signaling 9B11)` against target `LARP6` with annotation `nMYC` is
    correct by construction. Warning on it produced 15 false positives on GSE297587 and
    would have fired on every anti-V5 row of GSE290281 too.
    """

    def test_antibody_matching_the_tag_is_not_a_mismatch(self):
        assert validate_purification_agent(
            "Mouse Anti-Myc (Cell Signaling 9B11)", target="LARP6", annotation="nMYC"
        ) == []

    def test_v5_pulldown_of_tagged_rbp_is_not_a_mismatch(self):
        assert validate_purification_agent(
            "Rabbit Anti-V5 (Bethyl A190-120A)", target="LGALS3", annotation="cV5"
        ) == []

    def test_genuine_mismatch_still_warns(self):
        """No tag annotation → the antibody really should name the target."""
        issues = validate_purification_agent(
            "Rabbit Anti-TRIM25 (Thermo Fisher PA5-31650)", target="PARP13", annotation=""
        )
        assert issues and any(c.severity == WARNING for c in issues)

    def test_antibody_disagreeing_with_the_tag_still_warns(self):
        """Tagged row, but the antibody names neither the target nor the tag."""
        issues = validate_purification_agent(
            "Mouse Anti-FLAG (Sigma F1804)", target="LARP6", annotation="nMYC"
        )
        assert issues and any(c.severity == WARNING for c in issues)
