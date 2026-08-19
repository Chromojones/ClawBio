"""When a control has an antibody, the refusal must name the term that allows one.

GSE131210 (easyCLIP, Porter et al. 2021) has two HCT116 samples GEO describes as::

    Unmodified cells, immunopurified with anti-HA but without epitope

The antibody is real, named, and deliberately the same one used for the IPs; what is absent is
the epitope. The skill already has exactly the right term for this — `AbControl`, in
`ANTIBODY_CONTROL_TARGETS`, which *requires* an antibody rather than forbidding one.

Knowing that depends on already knowing it. The three obvious guesses are `SMInput`, `IgG` and
`noAbCtrl`, all of which mean *no antibody*, and all of which refuse with::

    control target noAbCtrl must have an empty purification agent, got 'Mouse Anti-HA (Sigma H3663)'

That message is true and complete about what is wrong and silent about what is right. Faced
with it, the obvious repairs are both damaging: drop the antibody to satisfy the gate, which
deletes the one fact the sample exists to record and turns an antibody control into a
beads-only control; or invent a new target such as `mockIP`, which passes with only a warning
and then reads downstream as a genuine IP against a protein of that name.

So the gate could push a careful person into mislabelling the sample. The fix is one clause:
when a control target refuses a non-empty agent, name `AbControl`.

The two terms are one word apart and mean opposite things — `noAbCtrl` is no antibody,
`AbControl` is an antibody against a target that is not there — so the pointer has to appear
exactly where the confusion happens.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
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
        """`no antibody` is a legacy spelling of an EMPTY agent, not a real antibody.
        Pointing it at `AbControl` would push correct-but-old data to the wrong target."""
        checks = validate_purification_agent("no antibody", target="noAbCtrl", annotation="")
        assert "AbControl" not in " ".join(c.message for c in checks)
        assert all(c.severity != ERROR for c in checks)
