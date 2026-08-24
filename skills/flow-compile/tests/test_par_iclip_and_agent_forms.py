"""Three gaps the GSE207656 and GSE131210 cleanups exposed.

**1. `PAR-iCLIP` is invisible to method inference.** GSE207656's series title is
*"PAR-iCLIP MCMV infection"*. The `PAR-CLIP` pattern is `par[\\s-]?clip`, which cannot match
`PAR-iCLIP` because the next token is `iclip`, not `clip`. Inference then reaches the plain
`iclip` pattern, matches the tail of the very same word, and returns `iCLIP`. All 9 samples
were labelled `iCLIP` for months.

That mislabel is not cosmetic. PAR-iCLIP is 4-thiouridine labelling with iCLIP library
chemistry, so it carries BOTH signals: the circularisation puts a truncation at the read 5'
end, and the 4sU adds T-to-C transitions the CLIP pipeline never scores. Recorded as `iCLIP`
the second signal is invisible; recorded as `PAR-CLIP` the first would be wrongly discarded.

**2. An antibody cannot state its reagent form.** `Anti-HA magnetic beads` is what the
GSE131210 methods describe, and the agent regex ends after the optional parenthetical, so the
trailing words fail to parse and the value is rejected outright. Recording bare `Anti-HA`
instead loses the fact that the pulldown used beads rather than a free antibody.

**3. A vendor with no catalog number is rejected.** GSE159997's antibody is
`Anti-CSDE1 (Invitrogen)`: the vendor is published, the catalog number is not. The parser
demands both, so a *more* informative value scores worse than the bare form it falls back to.
Vendor-without-catalog is a real, common state and must be expressible.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
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
        """The values this skill once synthesized must stay rejected."""
        assert normalize_purification_agent("CPSF5 antibody") == ""
        assert normalize_purification_agent("V5-antibody") == ""
