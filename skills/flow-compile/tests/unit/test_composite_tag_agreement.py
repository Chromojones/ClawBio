"""An antibody against one epitope of a composite tag agrees with it.

A tagged pulldown's antibody names the tag: anti-HA against `FLAG-HA-HIS` is correct (GSE131210,
41 rows), as is anti-FLAG against `3xFLAG`. Anti-HA against a FLAG-only construct still warns.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import WARNING, validate_purification_agent  # noqa: E402

HA = "Anti-HA"
FLAG = "Mouse Anti-FLAG (Sigma F1804)"
MYC = "Mouse Anti-Myc (Santa Cruz sc-40)"


def warnings(agent, target, annotation):
    return [c for c in validate_purification_agent(agent, target=target, annotation=annotation)
            if c.severity == WARNING and "check you took the antibody" in c.message]


class TestTheGse131210Rows:
    def test_anti_ha_against_an_fhh_tag_is_clean(self):
        assert warnings(HA, "hnRNPD", "nFLAG-HA-HIS") == []

    def test_anti_flag_against_an_fhh_tag_is_clean(self):
        assert warnings(FLAG, "hnRNPD", "nFLAG-HA-HIS") == []

    def test_a_mutant_row_is_clean(self):
        """The mutation prefix must not defeat component matching."""
        assert warnings(HA, "PCBP1", "100Q-nFLAG-HA-HIS") == []


class TestTheCheckStillBites:
    def test_anti_ha_against_a_flag_only_tag_still_warns(self):
        """SF3B1 is deposited as 3X FLAG tagged, with no HA epitope."""
        assert warnings(HA, "SF3B1", "n3xFLAG") != []

    def test_an_unrelated_antibody_still_warns(self):
        assert warnings(MYC, "hnRNPD", "nFLAG-HA-HIS") != []

    def test_an_untagged_target_still_warns(self):
        assert warnings(HA, "FBL", "") != []


class TestScaleEquivalence:
    def test_anti_flag_on_3xflag_is_clean(self):
        assert warnings(FLAG, "SF3B1", "n3xFLAG") == []

    def test_anti_flag_on_the_composite_3xflag_hbh_is_clean(self):
        assert warnings(FLAG, "X", "c3xFLAG-HBH") == []

    def test_the_simple_case_is_unchanged(self):
        assert warnings(MYC, "LARP6", "nMYC") == []
