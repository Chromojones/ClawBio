"""A repair is complete only when a re-read shows every sample correct.

`samples import` stores neither `purification_target__annotation` nor `source__annotation`, so
each direct-line study needs a post-import edit. A loop that counts its own edits reports success
when it dies partway (GSE131210: 11 of 34), so completion is measured by re-reading, and the plan
is rebuilt from observed state so a re-run converges.

Story: FAILURES.md#import-check
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_check import (  # noqa: E402
    RepairEdit,
    build_repair_plan,
    summarise_repair,
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


class TestReportingCompletion:
    def test_all_applied_is_complete(self):
        samples = [live(r["name"], annotation="nFLAG-HA-HIS", project="P1") for r in SHEET]
        result = summarise_repair(SHEET, samples, project_id="P1")
        assert result.complete is True

    def test_a_half_finished_repair_is_not_complete(self):
        samples = [live(SHEET[0]["name"], annotation="nFLAG-HA-HIS", project="P1"),
                   live(SHEET[1]["name"])]
        result = summarise_repair(SHEET, samples, project_id="P1")
        assert result.complete is False
        assert SHEET[1]["name"] in result.describe()

    def test_completion_ignores_how_many_edits_were_issued(self):
        """Edits issued is not evidence of completion."""
        samples = [live(SHEET[0]["name"], annotation="nFLAG-HA-HIS", project="P1"),
                   live(SHEET[1]["name"])]
        assert summarise_repair(SHEET, samples, project_id="P1", edits_applied=99).complete is False

    def test_fewer_samples_than_rows_is_not_complete(self):
        """Verifying only the samples you managed to read would pass on a truncated set."""
        samples = [live(SHEET[0]["name"], annotation="nFLAG-HA-HIS", project="P1")]
        result = summarise_repair(SHEET, samples, project_id="P1")
        assert result.complete is False
        assert "1" in result.describe() and "2" in result.describe()

    def test_the_description_warns_against_moving_on(self):
        samples = [live(SHEET[0]["name"], annotation="nFLAG-HA-HIS", project="P1"),
                   live(SHEET[1]["name"])]
        assert "execution" in summarise_repair(SHEET, samples, project_id="P1").describe().lower()
