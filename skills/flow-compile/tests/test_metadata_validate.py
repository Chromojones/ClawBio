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


class TestMutationTagAnnotation:
    """Protein alterations belong in the annotation, ahead of the tag.

    Flow renders `purification_target` + annotation as `TARGET:annotation`, so a
    myc-tagged LARP6 lacking its N-terminal region reads `LARP6:dNTR-nMYC`. Order is
    fixed: mutation first, tag last, hyphen-separated.
    """

    @pytest.mark.parametrize(
        "ann", ["dNTR-nMYC", "dNTD-nMYC", "dLaMod-nMYC", "dCTR-cV5", "R123A-c3xFLAG"]
    )
    def test_mutation_plus_tag_is_valid(self, ann):
        assert validate_target_and_annotation(target="LARP6", annotation=ann, agent="") == []

    def test_tag_only_still_valid(self):
        assert validate_target_and_annotation(target="LARP6", annotation="nMYC", agent="") == []

    def test_composite_tag_without_mutation_still_valid(self):
        """`c3xFLAG-HBH` is one tag, not mutation `c3xFLAG` plus tag `HBH`."""
        assert validate_target_and_annotation(
            target="QKI", annotation="c3xFLAG-HBH", agent=""
        ) == []

    def test_mutation_plus_composite_tag_is_valid(self):
        assert validate_target_and_annotation(
            target="QKI", annotation="dNTR-c3xFLAG-HBH", agent=""
        ) == []

    def test_tag_before_mutation_is_rejected(self):
        """Order is part of the convention — the tag must come last."""
        issues = validate_target_and_annotation(target="LARP6", annotation="nMYC-dNTR", agent="")
        assert issues and issues[0][0] == ERROR

    def test_mutation_without_a_tag_is_rejected(self):
        """An untagged mutant carries no tag annotation at all; use Condition instead."""
        issues = validate_target_and_annotation(target="LARP6", annotation="dNTR", agent="")
        assert issues and issues[0][0] == ERROR

class TestAntibodyWithoutAVendor:
    """When no catalog reagent exists, the agent is the bare canonical form.

    E-MTAB-1008 (Sugimoto 2012) immunoprecipitated Nova with an antibody the paper
    acknowledges as shared by Robert B Darnell. There is nothing to buy and no catalog to
    cite. Researcher convention: the agent stays `<Species> Anti-<TARGET>` and the
    provenance ("gift from X") is recorded in **Comments**, not inside the agent string.

    The vendor-less *prose* forms stay rejected — `NOVA antibody`, `anti-NOVA antibody`,
    `V5-antibody` are scraped phrasings that identify no reagent and signal an unfinished
    lookup, which is a different failure from a genuine gift antibody.
    """

    def test_bare_canonical_form_is_resolvable(self):
        assert normalize_purification_agent("Anti-Nova") == "Anti-NOVA"

    def test_species_is_kept_and_title_cased(self):
        assert normalize_purification_agent("rabbit anti-nova") == "Rabbit Anti-NOVA"

    def test_it_warns_so_the_researcher_confirms_no_catalog_reagent_exists(self):
        issues = validate_purification_agent("Anti-NOVA", target="Nova")
        assert not any(c.severity == ERROR for c in issues)
        assert any(c.severity == WARNING and "comment" in c.message.lower() for c in issues)

    def test_a_gift_parenthetical_is_migrated_out_of_the_agent(self):
        """One convention only: strip it, and say where provenance belongs."""
        assert normalize_purification_agent("Anti-Nova (gift: Robert B Darnell)") == "Anti-NOVA"
        issues = validate_purification_agent(
            "Anti-Nova (gift: Robert B Darnell)", target="Nova"
        )
        assert any(c.severity == WARNING and "comment" in c.message.lower() for c in issues)

    def test_target_agreement_still_applies(self):
        issues = validate_purification_agent("Anti-NOVA", target="NSUN2")
        assert any(c.severity == WARNING and "NSUN2" in c.message for c in issues)

    def test_tagged_pulldown_agreement_still_applies(self):
        """`Anti-Myc` against LARP6:nMYC is correct by construction — no MISMATCH warning.

        The vendor-less warning is still expected here; only the target-disagreement one
        must be absent.
        """
        issues = validate_purification_agent("Anti-Myc", target="LARP6", annotation="nMYC")
        assert not any("purification target is" in c.message for c in issues)

    def test_vendor_antibodies_are_unaffected_and_do_not_warn(self):
        assert (
            normalize_purification_agent("Rabbit Anti-PARP13 (Thermo Fisher, cat# PA5-31650)")
            == "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)"
        )
        assert validate_purification_agent(
            "Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)", target="PARP13"
        ) == []

    def test_vendorless_prose_forms_are_still_rejected(self):
        for bad in ("Nova antibody", "anti-NOVA antibody", "V5-antibody", "DHX9-mAb"):
            assert normalize_purification_agent(bad) == "", bad

    def test_empty_agent_on_an_ip_row_is_still_an_error(self):
        assert any(
            c.severity == ERROR for c in validate_purification_agent("", target="NOVA")
        )


class TestReplicateCollision:
    """Two rows sharing target + condition + replicate number means a distinction was lost.

    GSE290281's first batch uploaded all 4 runs of each protein as IPs, so the pair that were
    size-matched INPUTS carried the IP's target and antibody:

        RNPS1_Hs_HEK293T_Rep1_SRR32456785   <- IP        rep 1
        RNPS1_Hs_HEK293T_Rep1_SRR32456787   <- **input** rep 1, mislabelled

    The existing control check could not see this: it keys off the sample NAME containing
    'input'/'SMInput', and the naming step had failed in exactly the same way. A guardrail
    that depends on the field which is also wrong catches nothing.

    Replicate collision is name-independent evidence — two samples cannot both be replicate 1
    of the same target under the same condition. Condition must match too, or legitimate
    designs (GSE76475's RBFOX1 Rep1 in HMW *and* soluble fractions) would false-positive.
    """

    def _rows(self, specs):
        return pd.DataFrame([{
            "Sample Name": n, "Protein (Purification Target)": t, "Purification Agent": a,
            "Purification Target Annotation": "", "Cell or Tissue": "HEK293T",
            "Condition": c, "5' Barcode Sequence": "NNNNNNNNNN",
        } for n, t, a, c in specs])

    AGENT = "Rabbit Anti-V5 (Bethyl A190-120A)"

    def test_same_target_and_replicate_collides(self):
        df = self._rows([
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456785", "RNPS1", self.AGENT, ""),
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456787", "RNPS1", self.AGENT, ""),
        ])
        issues = validate_annotation_table(df)
        assert any(i.severity == ERROR and "replicate" in i.message.lower() for i in issues)

    def test_distinct_replicates_do_not_collide(self):
        df = self._rows([
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456785", "RNPS1", self.AGENT, ""),
            ("RNPS1_Hs_HEK293T_Rep2_SRR32456784", "RNPS1", self.AGENT, ""),
        ])
        assert not any("replicate" in i.message.lower() for i in validate_annotation_table(df))

    def test_same_replicate_under_different_conditions_is_legitimate(self):
        """GSE76475: RBFOX1 Rep1 exists in both nuclear fractions — not a collision."""
        df = self._rows([
            ("RBFOX1_Mm_Forebrain_Rep1", "RBFOX1", "Anti-RBFOX1", "HMW nuclear"),
            ("RBFOX1_Mm_Forebrain_Rep1_b", "RBFOX1", "Anti-RBFOX1", "Soluble nucleoplasm"),
        ])
        assert not any("replicate" in i.message.lower() for i in validate_annotation_table(df))

    def test_an_ip_and_its_properly_labelled_input_do_not_collide(self):
        """Once the input carries target SMInput, the targets differ, so no collision."""
        df = self._rows([
            ("RNPS1_HEK293T_Hs_IP_rep1", "RNPS1", self.AGENT, ""),
            ("RNPS1_HEK293T_Hs_INPUT_rep1", "SMInput", "", ""),
        ])
        assert not any("replicate" in i.message.lower() for i in validate_annotation_table(df))

    def test_rows_without_a_replicate_token_are_ignored(self):
        df = self._rows([
            ("RBFOX1_Mm_Forebrain_HMW_SRR1", "RBFOX1", "Anti-RBFOX1", "HMW nuclear"),
            ("RBFOX1_Mm_Hindbrain_HMW_SRR2", "RBFOX1", "Anti-RBFOX1", "HMW nuclear"),
        ])
        assert not any("replicate" in i.message.lower() for i in validate_annotation_table(df))

    def test_the_message_names_the_colliding_samples(self):
        df = self._rows([
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456785", "RNPS1", self.AGENT, ""),
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456787", "RNPS1", self.AGENT, ""),
        ])
        msgs = " ".join(i.message for i in validate_annotation_table(df))
        assert "SRR32456787" in msgs or "SRR32456785" in msgs

    def test_control_targets_are_exempt_from_collision(self):
        """SMInput is a shared placeholder, not a protein — every IP's input carries it.

        Without this exemption the check fires on every correctly-labelled study: GSE290281
        has 9 inputs, all target SMInput, so `SMInput + rep1` collides 5 ways in one batch.
        A guardrail that screams on correct data gets switched off, so the exemption matters
        as much as the check. Detection is unaffected — the bug it was written for had two
        rows carrying target RNPS1, not SMInput.
        """
        df = self._rows([
            ("CPSF5_HEK293T_Hs_INPUT_rep1", "SMInput", "", ""),
            ("CPSF6_HEK293T_Hs_INPUT_rep1", "SMInput", "", ""),
            ("EIF4B_HEK293T_Hs_INPUT_rep1", "SMInput", "", ""),
        ])
        assert not any("replicate" in i.message.lower() for i in validate_annotation_table(df))

    def test_igg_and_input_are_exempt_too(self):
        for control in ("IgG", "INPUT"):
            df = self._rows([
                (f"A_{control}_rep1", control, "", ""),
                (f"B_{control}_rep1", control, "", ""),
            ])
            assert not any(
                "replicate" in i.message.lower() for i in validate_annotation_table(df)
            ), control

    def test_real_ip_collision_still_detected_alongside_controls(self):
        """The exemption must not mask the bug it was built for."""
        df = self._rows([
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456785", "RNPS1", self.AGENT, ""),
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456787", "RNPS1", self.AGENT, ""),
            ("CPSF5_HEK293T_Hs_INPUT_rep1", "SMInput", "", ""),
            ("CPSF6_HEK293T_Hs_INPUT_rep1", "SMInput", "", ""),
        ])
        hits = [i for i in validate_annotation_table(df) if "replicate" in i.message.lower()]
        assert len(hits) == 1 and "RNPS1" in hits[0].message

    def test_same_target_different_tag_is_not_a_collision(self):
        """E-MTAB-2700 expresses each target as BOTH a T7- and a GFP-tagged construct.

        `APOBEC3G` + `producer cell` + replicate 1 exists twice — once as `nT7`, once as
        `nGFP`. Nothing is lost: Flow renders `TARGET:annotation`, so the tag is part of the
        sample's identity and the two rows are fully distinguishable. Keying the check on
        target+condition+replicate alone flagged all 12 of them, which would have pushed the
        tag into `Condition` purely to satisfy the check — contorting the data around a
        guardrail instead of fixing it.
        """
        df = self._rows([
            ("APOBEC3G_T7_rep1", "APOBEC3G", "Anti-T7", "producer cell"),
            ("APOBEC3G_GFP_rep1", "APOBEC3G", "Anti-GFP", "producer cell"),
        ])
        df["Purification Target Annotation"] = ["nT7", "nGFP"]
        assert not any("replicate" in i.message.lower() for i in validate_annotation_table(df))

    def test_same_target_same_tag_still_collides(self):
        """The tag must discriminate only when it actually differs."""
        df = self._rows([
            ("APOBEC3G_T7_rep1_a", "APOBEC3G", "Anti-T7", "producer cell"),
            ("APOBEC3G_T7_rep1_b", "APOBEC3G", "Anti-T7", "producer cell"),
        ])
        df["Purification Target Annotation"] = ["nT7", "nT7"]
        assert any("replicate" in i.message.lower() for i in validate_annotation_table(df))

    def test_gse290281_inputs_still_collide_with_their_ips(self):
        """Regression: the bug this check was built for shared a tag, so it must still fire."""
        df = self._rows([
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456785", "RNPS1", self.AGENT, ""),
            ("RNPS1_Hs_HEK293T_Rep1_SRR32456787", "RNPS1", self.AGENT, ""),
        ])
        df["Purification Target Annotation"] = ["cV5", "cV5"]
        assert any("replicate" in i.message.lower() for i in validate_annotation_table(df))


class TestT7Tag:
    """T7 is a standard epitope tag and must be in the vocabulary.

    E-MTAB-2700 (Apolonia 2015) expresses APOBEC3G/3F as both T7- and GFP-tagged
    constructs, immunoprecipitated with anti-T7 (Novagen) or anti-GFP (Roche). Half the
    study is T7-tagged, and `nT7` was rejected as invalid tag grammar purely because the
    vocabulary listed FLAG/GFP/V5/HA/MYC/HBH/HIS/TAP/SNAP/HALO/MS2 but not T7.

    The tag is the T7 gene 10 leader peptide (MASMTGGQQMG) — as standard as FLAG.
    """

    def test_t7_is_valid_at_either_terminus(self):
        for ann in ("nT7", "cT7"):
            assert validate_target_and_annotation(
                target="APOBEC3G", annotation=ann, agent="Anti-T7"
            ) == [], ann

    def test_t7_composes_with_a_mutation_prefix(self):
        assert validate_target_and_annotation(
            target="APOBEC3G", annotation="dCTD-nT7", agent="Anti-T7"
        ) == []

    def test_an_anti_t7_pulldown_of_a_t7_tagged_target_is_not_a_mismatch(self):
        issues = validate_purification_agent("Anti-T7", target="APOBEC3G", annotation="nT7")
        assert not any("purification target is" in c.message for c in issues)

    def test_bare_t7_without_a_terminus_is_still_rejected(self):
        issues = validate_target_and_annotation(target="APOBEC3G", annotation="T7", agent="")
        assert issues and issues[0][0] == ERROR

    def test_existing_tags_still_work(self):
        for ann in ("cV5", "nMYC", "c3xFLAG-HBH", "nGFP"):
            assert validate_target_and_annotation(target="QKI", annotation=ann, agent="") == [], ann
