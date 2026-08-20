"""A cross-check that compares nothing must not report agreement.

Before submitting a CLIP execution the submitter resolves 21 reference files from the genome
prep execution, then cross-checks them against a *completed* run of the same organism — two
independent sources, so a silently wrong reference cannot reach the pipeline. It is a good
check and it has the same hole the platform-wide duplicate search once had::

    shared = set(prep) & set(reference_run)
    if any(prep[k] != reference_run[k] for k in shared): refuse

When the two executions share no keys, ``shared`` is empty, no comparison happens, and the
submitter prints ``0 cross-checked`` and proceeds. Zero disagreements is not agreement.

Two live ways to reach that state:

- **The reference run is a different organism.** GSE63262 is the first *Drosophila* study, so
  there is no completed fly CLIP run; the constant still pointed at a mouse execution
  (`413563648057607928`) inherited from the previous study's script. Mouse and fly happen to
  share key names, so this one refuses loudly — but only by luck of the key naming.
- **The reference run's `data_params` is shaped differently** — empty, or keyed by file id
  rather than role. Then the intersection really is empty and the check evaporates.

The distinction that matters is between *agreed*, *disagreed*, and *not compared*, and the
third must never be reported as the first. When there is genuinely no completed run to compare
against — which is the normal state for the first study of any organism — that has to be an
explicit, recorded decision, not the accidental output of an empty set intersection.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.reference_cross_check import cross_check_reference  # noqa: E402

PREP = {"fasta": "111", "gtf": "222", "star": "333"}


class TestAgreement:
    def test_identical_ids_agree(self):
        result = cross_check_reference(PREP, dict(PREP))
        assert result.ok is True
        assert result.compared == 3

    def test_a_differing_id_is_refused(self):
        result = cross_check_reference(PREP, {**PREP, "gtf": "999"})
        assert result.ok is False
        assert "gtf" in result.describe()

    def test_ids_are_compared_as_strings(self):
        """One source returns ints, the other strings; that is not a mismatch."""
        assert cross_check_reference({"fasta": 111}, {"fasta": "111"}).ok is True


class TestTheEmptyIntersection:
    def test_no_shared_keys_is_not_agreement(self):
        result = cross_check_reference(PREP, {"genome_fa": "111", "annotation": "222"})
        assert result.ok is False
        assert result.compared == 0

    def test_an_empty_reference_is_not_agreement(self):
        result = cross_check_reference(PREP, {})
        assert result.ok is False

    def test_the_message_says_nothing_was_compared(self):
        text = cross_check_reference(PREP, {}).describe().lower()
        assert "0" in text or "no " in text
        assert "not" in text

    def test_it_does_not_read_as_a_pass(self):
        """`0 cross-checked` printed beside a proceeding submit is the whole bug."""
        assert cross_check_reference(PREP, {}).ok is False


class TestTheFirstStudyOfAnOrganism:
    def test_absence_must_be_declared_not_inferred(self):
        """GSE63262 is the first Drosophila study — there is no fly run to compare against."""
        result = cross_check_reference(PREP, None, no_reference_run_reason="")
        assert result.ok is False

    def test_a_declared_reason_is_accepted_and_recorded(self):
        result = cross_check_reference(
            PREP, None,
            no_reference_run_reason="first Drosophila CLIP study; no completed fly run exists")
        assert result.ok is True
        assert result.compared == 0
        assert "first Drosophila" in result.describe()

    def test_a_declared_reason_still_reports_it_was_unverified(self):
        result = cross_check_reference(PREP, None, no_reference_run_reason="first fly study")
        assert "single source" in result.describe().lower() or "unverified" in result.describe().lower()

    def test_a_reason_cannot_excuse_an_actual_disagreement(self):
        """If a reference run WAS supplied, the reason must not suppress a real mismatch."""
        result = cross_check_reference(
            PREP, {**PREP, "gtf": "999"}, no_reference_run_reason="first fly study")
        assert result.ok is False
