"""A cross-check that compares nothing does not report agreement.

Two reference mappings that share no keys give zero disagreements, which is not agreement.
Agreed, disagreed and not compared are separate outcomes, and the first study of an organism
(GSE63262, Drosophila) must state why nothing was compared.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
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
        """`0 cross-checked` is not a pass."""
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

    def test_the_described_filename_count_matches_what_was_actually_resolved(self):
        """`describe()` used to say "The 21 filenames" unconditionally — a leftover from
        whatever run the message was first written against, unrelated to `PREP`'s actual size
        (3 keys here). GSE149561 resolves 5 pipeline params, not 21; a message with the wrong
        count is worse than no count.
        """
        result = cross_check_reference(PREP, None, no_reference_run_reason="first fly study")
        assert f"The {len(PREP)} filenames" in result.describe()
        assert "21 filenames" not in result.describe()

    def test_a_declared_reason_still_reports_it_was_unverified(self):
        result = cross_check_reference(PREP, None, no_reference_run_reason="first fly study")
        assert "single source" in result.describe().lower() or "unverified" in result.describe().lower()

    def test_a_reason_cannot_excuse_an_actual_disagreement(self):
        """If a reference run WAS supplied, the reason must not suppress a real mismatch."""
        result = cross_check_reference(
            PREP, {**PREP, "gtf": "999"}, no_reference_run_reason="first fly study")
        assert result.ok is False
