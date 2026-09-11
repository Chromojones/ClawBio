"""`noAbCtrl` is a control target distinct from `SMInput`.

`SMInput` is input material carried through the protocol; `noAbCtrl` is a pulldown with no
antibody (GSE75418's beads-only sample). Both take an empty `purification_agent`.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import (  # noqa: E402
    CONTROL_TARGETS,
    ERROR,
    validate_purification_agent,
    validate_target_and_annotation,
)


class TestTheVocabulary:
    def test_noabctrl_is_a_control_target(self):
        assert "NOABCTRL" in CONTROL_TARGETS

    def test_the_existing_control_targets_are_untouched(self):
        assert {"SMINPUT", "INPUT", "IGG"} <= CONTROL_TARGETS


class TestTheGse75418Row:
    def test_an_empty_agent_is_accepted(self):
        """The row's entire meaning is that no antibody was used."""
        assert validate_purification_agent("", target="noAbCtrl", annotation="") == []

    def test_the_target_validates(self):
        checks = validate_target_and_annotation(
            target="noAbCtrl", annotation="", agent="", sample_name="noAbCtrl_SHSY5Y_Hs_rep1")
        assert [c for c in checks if c.severity == ERROR] == []

    def test_case_is_not_significant(self):
        assert validate_purification_agent("", target="NOABCTRL", annotation="") == []
        assert validate_purification_agent("", target="noabctrl", annotation="") == []


class TestItStaysDistinctFromSMInput:
    def test_carrying_the_ip_protein_is_still_refused(self):
        """A control must not claim to have pulled down the protein."""
        checks = validate_target_and_annotation(
            target="noAbCtrl", annotation="nFLAG", agent="", sample_name="x")
        assert any(c.severity == ERROR for c in checks)

    def test_a_real_antibody_on_a_no_antibody_control_is_refused(self):
        """`noAbCtrl` + an antibody is a contradiction in terms."""
        checks = validate_purification_agent(
            "Rabbit Anti-SAFB1 (Bethyl A300-811A)", target="noAbCtrl", annotation="")
        assert any(c.severity == ERROR for c in checks)

    def test_a_real_target_still_requires_an_agent(self):
        """The check that noAbCtrl exempts must keep firing everywhere else."""
        checks = validate_purification_agent("", target="SAFB1", annotation="")
        assert any(c.severity == ERROR for c in checks)
