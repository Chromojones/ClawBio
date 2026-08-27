"""A repair that stops halfway looks exactly like one that finished.

Every SRA-direct study needs the same fix-up after import: ``samples import`` accepts
``purification_target__annotation`` and ``source__annotation``, stores neither, and attaches no
project. `import_verify` finds those gaps; something has to close them.

The closing loop is itself a failure point. On GSE131210 a 34-sample repair died at sample 11
with::

    urllib.error.URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>

leaving 11 samples correct and 23 untouched — and nothing said so. The loop had reported its
own progress rather than re-reading the study, so "I wrote 11 edits" was the only evidence
available, and it reads as success. This is the third transient disconnect in the ledger, so
it is a normal event, not an exotic one.

Two rules fall out, and both are about not trusting the writer:

1. **Completion is measured by re-reading every sample**, never by counting edits issued. A
   plan of 34 with 11 applied is INCOMPLETE, and must say so loudly enough that nobody moves
   on to submitting an execution.
2. **The plan is rebuilt from observed state**, so re-running is safe and cheap: samples
   already correct are skipped, and a resumed run converges rather than rewriting everything.

`import_verify.find_import_discrepancies` already reports sheet rows with no matching sample,
so it would have caught the partial state had it been called. This module exists so that
calling it is the only way to declare the repair done.
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
        """The GSE131210 shape: some done, some untouched."""
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
        """The crash reported 11 writes and was 23 short. Edits issued is not evidence."""
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
