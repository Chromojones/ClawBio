"""PAR-iCLIP detection, and two agent forms.

`PAR-iCLIP` is 4sU labelling with iCLIP chemistry, carrying both truncation and T-to-C signals;
`iclip` must not match the tail of the word (GSE207656). An agent may state its reagent form
(`Anti-HA magnetic beads`) or a vendor without a catalog (`Anti-CSDE1 (Invitrogen)`).

Story: FAILURES.md#protocol-detection
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.flow_annotate import infer_experimental_method  # noqa: E402
from lib.metadata_validate import (  # noqa: E402
    ERROR,
    WARNING,
    normalize_purification_agent,
    validate_purification_agent,
)


class TestParICLIP:
    def test_the_gse207656_title_resolves(self):
        assert infer_experimental_method("", "PAR-iCLIP MCMV infection") == "PAR-iCLIP"

    def test_it_is_not_swallowed_by_the_plain_iclip_pattern(self):
        """The bug: `iclip` matches the tail of `PAR-iCLIP`."""
        assert infer_experimental_method("PAR-iCLIP was performed using 4-thiouridine") == "PAR-iCLIP"

    def test_spacing_variants(self):
        for text in ("PAR iCLIP", "par-iclip", "PARiCLIP"):
            assert infer_experimental_method("", text) == "PAR-iCLIP", text

    def test_classic_par_clip_is_unchanged(self):
        assert infer_experimental_method("", "PAR-CLIP of QKI") == "PAR-CLIP"

    def test_plain_iclip_is_unchanged(self):
        assert infer_experimental_method("", "iCLIP of LARP6") == "iCLIP"

    def test_the_other_flavours_are_unchanged(self):
        assert infer_experimental_method("", "irCLIP of ELAVL1") == "irCLIP"
        assert infer_experimental_method("", "eCLIP of PARP13") == "eCLIP"


class TestReagentForm:
    def test_magnetic_beads_parse(self):
        assert normalize_purification_agent("Anti-HA magnetic beads") == "Anti-HA magnetic beads"

    def test_it_validates_against_a_tagged_target(self):
        checks = validate_purification_agent(
            "Anti-HA magnetic beads", target="CELF1", annotation="nFLAG-HA-HIS")
        assert [c for c in checks if c.severity == ERROR] == []

    def test_other_forms_parse(self):
        for form in ("Anti-FLAG M2 magnetic beads", "Anti-GFP agarose",
                     "Anti-Myc Dynabeads", "Anti-V5 resin", "Anti-HA sepharose"):
            assert normalize_purification_agent(form), form

    def test_the_target_is_still_extracted(self):
        from lib.metadata_validate import agent_target
        assert agent_target("Anti-HA magnetic beads") == "HA"

    def test_junk_after_the_target_is_still_refused(self):
        """Only known reagent forms are allowed, not arbitrary trailing prose."""
        assert normalize_purification_agent("Anti-HA which we got from a freezer") == ""


class TestVendorWithoutCatalog:
    def test_it_parses(self):
        assert normalize_purification_agent("Anti-CSDE1 (Invitrogen)") == "Anti-CSDE1 (Invitrogen)"

    def test_it_is_accepted_with_a_warning_not_an_error(self):
        checks = validate_purification_agent("Anti-CSDE1 (Invitrogen)", target="CSDE1")
        assert [c for c in checks if c.severity == ERROR] == []
        assert any(c.severity == WARNING for c in checks)

    def test_the_warning_says_the_catalog_is_missing(self):
        checks = validate_purification_agent("Anti-CSDE1 (Invitrogen)", target="CSDE1")
        assert "catalog" in " ".join(c.message for c in checks).lower()

    def test_species_and_vendor_without_catalog(self):
        assert normalize_purification_agent("Rabbit Anti-FBL (Bethyl)") == "Rabbit Anti-FBL (Bethyl)"

    def test_a_full_vendor_and_catalog_is_still_clean(self):
        checks = validate_purification_agent(
            "Rabbit Anti-FBL (Bethyl A303-891A)", target="FBL")
        assert checks == []

    def test_the_generic_forms_are_still_refused(self):
        """Generic synthesized forms stay rejected."""
        assert normalize_purification_agent("CPSF5 antibody") == ""
        assert normalize_purification_agent("V5-antibody") == ""
