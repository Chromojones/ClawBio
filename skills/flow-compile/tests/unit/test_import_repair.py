"""The post-import repair plan.

`samples import` stores neither `purification_target__annotation` nor `source__annotation`, so
each direct-line study needs a post-import edit. The plan is built from observed state: a re-run
plans only what is still wrong, and a missing sample is a failed import, not a repair.

Story: FAILURES.md#import-check
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_check import (  # noqa: E402
    RepairEdit,
    build_repair_plan,
)

SHEET = [
    {"accession": "SRX5830818", "name": "hnRNPD_HEK293T_Hs_rep1_SRX5830818",
     "purification_target": "hnRNPD", "purification_target__annotation": "nFLAG-HA-HIS",
     "source": "HEK293T", "source__annotation": "", "purification_agent": "Anti-HA"},
    {"accession": "SRX5830819", "name": "hnRNPD_HEK293T_Hs_rep2_SRX5830819",
     "purification_target": "hnRNPD", "purification_target__annotation": "nFLAG-HA-HIS",
     "source": "HEK293T", "source__annotation": "", "purification_agent": "Anti-HA"},
]


def live(name, *, annotation="", project=None, agent="Anti-HA"):
    """A sample body in the shape `GET /api/samples/{id}` actually returns."""
    return {
        "id": f"id-{name}", "name": name,
        "project": {"id": project} if project else None,
        "metadata": {
            "purification_target": {"value": "hnRNPD", "annotation": annotation},
            "source": {"value": "HEK293T", "annotation": ""},
            "purification_agent": {"value": agent, "annotation": ""},
        },
    }


class TestBuildingThePlan:
    def test_a_dropped_annotation_becomes_an_edit(self):
        samples = [live(r["name"]) for r in SHEET]
        plan = build_repair_plan(SHEET, samples, project_id="P1")
        assert len(plan) == 2
        assert all(isinstance(e, RepairEdit) for e in plan)
        assert plan[0].fields["purification_target__annotation"] == "nFLAG-HA-HIS"

    def test_the_project_is_included_when_unattached(self):
        plan = build_repair_plan(SHEET, [live(r["name"]) for r in SHEET], project_id="P1")
        assert plan[0].fields["project"] == "P1"

    def test_a_correct_sample_needs_no_edit(self):
        """Re-running must converge, not rewrite everything."""
        samples = [live(r["name"], annotation="nFLAG-HA-HIS", project="P1") for r in SHEET]
        assert build_repair_plan(SHEET, samples, project_id="P1") == []

    def test_a_partially_repaired_study_plans_only_the_remainder(self):
        """Some samples done, some untouched: plan only the rest."""
        samples = [live(SHEET[0]["name"], annotation="nFLAG-HA-HIS", project="P1"),
                   live(SHEET[1]["name"])]
        plan = build_repair_plan(SHEET, samples, project_id="P1")
        assert [e.name for e in plan] == [SHEET[1]["name"]]

    def test_a_missing_sample_is_not_silently_skipped(self):
        """A sheet row with no sample is a failed import, not a finished repair."""
        plan = build_repair_plan(SHEET, [live(SHEET[0]["name"])], project_id="P1")
        assert any(e.missing for e in plan)


