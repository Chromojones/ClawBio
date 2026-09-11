"""Two result shapes: `Finding` (one problem, in a list) and `Verdict` (one question answered,
with evidence).

`Finding` indexes as `(severity, message)` because the metadata tests read it positionally.

Story: FAILURES.md#result-type-sprawl
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.results import (  # noqa: E402
    ERROR,
    INFO,
    WARNING,
    Finding,
    Verdict,
    blocking,
    render_findings,
)


class TestFindingIsTheOldCheck:
    def test_positional_access_matches_the_namedtuple(self):
        """`issues[0][0] == ERROR` is how the metadata tests read findings."""
        f = Finding(ERROR, "bad antibody", field="Purification Agent")
        assert f[0] == ERROR
        assert f[1] == "bad antibody"
        assert f[2] == "Purification Agent"

    def test_unpacking_still_works(self):
        severity, message = Finding(WARNING, "no catalog")
        assert (severity, message) == (WARNING, "no catalog")

    def test_attribute_access(self):
        f = Finding(ERROR, "m", field="F")
        assert (f.severity, f.message, f.field) == (ERROR, "m", "F")

    def test_field_defaults_empty_like_the_namedtuple(self):
        assert Finding(ERROR, "m").field == ""

    def test_out_of_range_index_raises(self):
        try:
            Finding(ERROR, "m")[9]
        except IndexError:
            return
        raise AssertionError("expected IndexError")


class TestFindingCarriesTheOtherShapes:
    def test_metadata_issue_fields(self):
        f = Finding(ERROR, "m", field="Organism", row=3, subject="SAMPLE_1")
        assert (f.row, f.subject) == (3, "SAMPLE_1")

    def test_discrepancy_fields(self):
        """A discrepancy carries expected and actual."""
        f = Finding(ERROR, "annotation dropped", subject="S1",
                    field="purification_target__annotation", expected="nFLAG", actual="")
        assert f.expected == "nFLAG" and f.actual == ""

    def test_defaults_are_not_shared_between_instances(self):
        a, b = Finding(ERROR, "a"), Finding(ERROR, "b")
        assert a.field == b.field == ""
        assert a is not b


class TestBlocking:
    def test_only_errors_block(self):
        found = [Finding(ERROR, "a"), Finding(WARNING, "b"), Finding(INFO, "c")]
        assert [f.message for f in blocking(found)] == ["a"]

    def test_empty_is_not_blocking(self):
        assert blocking([]) == []


class TestVerdict:
    def test_ok_verdict(self):
        assert Verdict(True).ok is True

    def test_reason_and_evidence(self):
        v = Verdict(False, "0 files overlapped", evidence={"compared": 0})
        assert v.evidence["compared"] == 0
        assert "overlapped" in v.describe()

    def test_describe_distinguishes_not_compared_from_agreed(self):
        """The distinction reference_cross_check exists to preserve: zero disagreements
        is not agreement."""
        agreed = Verdict(True, evidence={"compared": 21})
        not_compared = Verdict(False, "not compared: 0 files overlapped", evidence={"compared": 0})
        assert agreed.describe() != not_compared.describe()
        assert "not compared" in not_compared.describe().lower()

    def test_evidence_defaults_are_not_shared(self):
        a, b = Verdict(True), Verdict(True)
        a.evidence["x"] = 1
        assert b.evidence == {}


class TestRenderFindings:
    def test_it_reports_the_total_not_just_the_failures(self):
        """The report leads with "N of M"; a bare failure list hides how much was checked."""
        out = render_findings([Finding(ERROR, "bad")], title="Import check", total=24)
        assert "24" in out and "1" in out

    def test_a_clean_result_says_so(self):
        out = render_findings([], title="Import check", total=24)
        assert "24" in out
        assert "no" in out.lower() or "0" in out

    def test_the_subject_appears(self):
        out = render_findings([Finding(ERROR, "bad", subject="SAMPLE_7")], title="t", total=1)
        assert "SAMPLE_7" in out
