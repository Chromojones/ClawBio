"""A control refused for carrying an antibody is pointed at `AbControl`.

`noAbCtrl`, `SMInput` and `IgG` take no antibody; `AbControl` requires one, against a target that
is absent (GSE131210: anti-HA on unmodified cells). Without the pointer, the obvious repairs are
deleting the antibody or inventing a target.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import (  # noqa: E402
    ANTIBODY_CONTROL_TARGETS,
    CONTROL_TARGETS,
    ERROR,
    validate_purification_agent,
)

HA = "Mouse Anti-HA (Sigma H3663)"


class TestTheTermAlreadyExists:
    def test_abcontrol_is_the_antibody_bearing_control(self):
        assert "ABCONTROL" in ANTIBODY_CONTROL_TARGETS

    def test_it_is_not_one_of_the_no_antibody_controls(self):
        assert "ABCONTROL" not in CONTROL_TARGETS

    def test_the_gse131210_row_validates_under_it(self):
        assert validate_purification_agent(HA, target="AbControl", annotation="") == []

    def test_abcontrol_without_an_antibody_is_still_refused(self):
        checks = validate_purification_agent("", target="AbControl", annotation="")
        assert any(c.severity == ERROR for c in checks)


class TestTheRefusalPointsSomewhere:
    def test_noabctrl_with_an_antibody_names_abcontrol(self):
        checks = validate_purification_agent(HA, target="noAbCtrl", annotation="")
        assert any(c.severity == ERROR for c in checks)
        assert "AbControl" in " ".join(c.message for c in checks)

    def test_igg_with_an_antibody_names_abcontrol(self):
        checks = validate_purification_agent(HA, target="IgG", annotation="")
        assert "AbControl" in " ".join(c.message for c in checks)

    def test_sminput_with_an_antibody_names_abcontrol(self):
        checks = validate_purification_agent(HA, target="SMInput", annotation="")
        assert "AbControl" in " ".join(c.message for c in checks)

    def test_the_original_complaint_survives(self):
        """The pointer is added to the message, it does not replace it."""
        message = " ".join(
            c.message for c in validate_purification_agent(HA, target="noAbCtrl", annotation=""))
        assert "empty purification agent" in message
        assert "Mouse Anti-HA (Sigma H3663)" in message

    def test_the_legacy_no_antibody_literal_is_not_redirected(self):
        """`no antibody` spells an empty agent; pointing it at `AbControl` would be wrong."""
        checks = validate_purification_agent("no antibody", target="noAbCtrl", annotation="")
        assert "AbControl" not in " ".join(c.message for c in checks)
        assert all(c.severity != ERROR for c in checks)
