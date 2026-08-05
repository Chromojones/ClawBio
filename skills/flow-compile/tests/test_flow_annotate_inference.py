"""Hardening for the two biggest judgement surfaces in annotation building.

`infer_protein_target` fed a confidently-wrong non-empty value into four downstream
places (purification agent, sample name, target annotation, barcode replicate logic), and
`infer_experimental_method` could reroute an entire study through the wrong protocol
branch on one word of boilerplate prose.
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.flow_annotate import (  # noqa: E402
    infer_experimental_method,
    infer_protein_target,
)


class TestProteinTargetRejectsNonTargets:
    """The comma-lead branch used to return the first token unconditionally."""

    def test_cell_line_lead_is_not_a_target(self):
        assert infer_protein_target("HeLa, PTBP1 eCLIP, rep1") != "HELA"

    def test_cell_line_lead_falls_through_to_the_real_target(self):
        assert infer_protein_target("K562, RBFOX2, rep 1") == "RBFOX2"

    @pytest.mark.parametrize(
        "char",
        [
            "antibody: rabbit anti-PARP13 (Thermo PA5-31650)",
            "antibody: goat anti-QKI",
        ],
    )
    def test_species_from_antibody_characteristic_is_not_a_target(self, char):
        assert infer_protein_target("some title", [char]) not in {"RABBIT", "GOAT"}

    def test_anti_prefix_is_not_a_target(self):
        assert not infer_protein_target("x", ["antibody: anti-FLAG M2"]).startswith("ANTI")

    def test_real_gene_symbol_still_resolves(self):
        assert infer_protein_target("PARP13, HEK293T, replicate 1 eCLIP") == "PARP13"
        assert infer_protein_target("iCLIP-DHX9-1") == "DHX9"


class TestProteinTargetControls:
    """eCLIP inputs are their own target — never the IP's protein."""

    @pytest.mark.parametrize(
        "title",
        [
            "PARP13, HEK293T, input, replicate 1",
            "RBFOX2 SMInput rep2",
            "CPSF5, K562, size-matched input",
        ],
    )
    def test_input_rows_resolve_to_sminput(self, title):
        assert infer_protein_target(title) == "SMInput"

    def test_igg_control_is_not_the_ip_protein(self):
        assert infer_protein_target("PTBP1, HeLa, IgG control") == "IgG"

    def test_ip_row_of_the_same_study_is_unaffected(self):
        assert infer_protein_target("PARP13, HEK293T, replicate 1") == "PARP13"

    def test_sminput_target_puts_input_in_the_sample_name(self):
        """The SMInput validator keys off an INPUT token in the name — it must appear."""
        from lib.sample_naming import build_flow_sample_name

        target = infer_protein_target("PARP13, HEK293T, input, rep1")
        name = build_flow_sample_name(target, "HEK293T", "Hs", "input rep1", "SRR1")
        assert "INPUT" in name.upper()


class TestExperimentalMethod:
    def test_flash_frozen_prose_does_not_make_it_a_flash_study(self):
        """'cells were flash-frozen' is boilerplate in almost every extract protocol."""
        protocol = "Cells were flash-frozen in liquid nitrogen. iCLIP was performed as described."
        assert infer_experimental_method(protocol) == "iCLIP"

    def test_real_flash_study_still_detected(self):
        assert infer_experimental_method("FLASH libraries were prepared") == "FLASH"

    def test_series_title_outranks_protocol_prose(self):
        """The title names the assay; the protocol often cites other protocols."""
        protocol = "Libraries were prepared as described for eCLIP (Van Nostrand 2016)."
        assert infer_experimental_method(protocol, "DHX9 iCLIP in HeLa") == "iCLIP"

    def test_eclip_title_wins_over_iclip_lineage_mention(self):
        protocol = "eCLIP builds on the iCLIP method."
        assert infer_experimental_method(protocol, "PARP13 eCLIP") == "eCLIP"

    def test_seclip_is_distinguished_from_eclip(self):
        assert infer_experimental_method("", "RBFOX2 seCLIP") == "seCLIP"

    def test_iclip2_still_wins(self):
        assert infer_experimental_method("iCLIP2 protocol was used") == "iCLIP2"

    def test_unknown_protocol_still_defaults_to_iclip(self):
        assert infer_experimental_method("some unrelated protocol") == "iCLIP"
