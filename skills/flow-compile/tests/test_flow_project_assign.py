"""Tests for post-import project assignment.

`flowbio samples import --sheet` has no project field (RESERVED_COLUMNS is
accession/name/organism/sample_type), so imported samples land unattached and must be
assigned in a second step via POST /samples/{id}/edit.
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.flow_project_assign import (  # noqa: E402
    assign_samples_to_project,
    build_assignment_plan,
)


class FakeApi:
    """Records the calls a real client would make to the Flow REST API."""

    def __init__(self, samples=None, fail_ids=()):
        self.samples = samples or {}
        self.fail_ids = set(fail_ids)
        self.edits = []

    def get_sample(self, sample_id):
        return self.samples.get(str(sample_id), {"id": str(sample_id), "project": None})

    def edit_sample(self, sample_id, body):
        if str(sample_id) in self.fail_ids:
            raise RuntimeError("HTTP 500")
        self.edits.append((str(sample_id), body))
        self.samples.setdefault(str(sample_id), {})["project"] = {"id": body.get("project")}
        return {"id": str(sample_id)}


class TestBuildAssignmentPlan:
    def test_unattached_samples_are_planned(self):
        api = FakeApi({"1": {"project": None}, "2": {"project": None}})
        plan = build_assignment_plan(api, ["1", "2"], "PROJ")
        assert [p.sample_id for p in plan] == ["1", "2"]
        assert all(p.needs_change for p in plan)

    def test_already_attached_sample_is_a_noop(self):
        api = FakeApi({"1": {"project": {"id": "PROJ"}}})
        plan = build_assignment_plan(api, ["1"], "PROJ")
        assert plan[0].needs_change is False

    def test_sample_in_a_different_project_is_flagged(self):
        api = FakeApi({"1": {"project": {"id": "OTHER"}}})
        plan = build_assignment_plan(api, ["1"], "PROJ")
        assert plan[0].needs_change is True
        assert plan[0].current_project == "OTHER"


class TestAssignSamples:
    def test_dry_run_makes_no_edits(self):
        api = FakeApi({"1": {"project": None}})
        result = assign_samples_to_project(api, ["1"], "PROJ", dry_run=True)
        assert api.edits == []
        assert result.planned == 1 and result.assigned == 0

    def test_assignment_posts_project_id(self):
        api = FakeApi({"1": {"project": None}, "2": {"project": None}})
        result = assign_samples_to_project(api, ["1", "2"], "PROJ")
        assert result.assigned == 2
        assert api.edits == [("1", {"project": "PROJ"}), ("2", {"project": "PROJ"})]

    def test_already_attached_is_skipped_not_reposted(self):
        api = FakeApi({"1": {"project": {"id": "PROJ"}}})
        result = assign_samples_to_project(api, ["1"], "PROJ")
        assert api.edits == []
        assert result.skipped == 1

    def test_failures_are_counted_and_do_not_abort_the_batch(self):
        api = FakeApi({"1": {"project": None}, "2": {"project": None}}, fail_ids={"1"})
        result = assign_samples_to_project(api, ["1", "2"], "PROJ")
        assert result.failed == 1
        assert result.assigned == 1
        assert "1" in result.failures

    def test_empty_project_id_is_rejected(self):
        api = FakeApi({"1": {"project": None}})
        with pytest.raises(ValueError, match="project"):
            assign_samples_to_project(api, ["1"], "")
