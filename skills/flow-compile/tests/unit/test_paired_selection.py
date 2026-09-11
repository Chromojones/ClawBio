"""`paired=first`/`second` on single-end data produces an empty samplesheet.

The pipeline then fails with `Invalid number of populated columns`, which never mentions mates
(GSE75418, GSE68800). ENA's `library_layout` makes it checkable before submission.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_guards import check_paired_selection  # noqa: E402


class TestSingleEnd:
    def test_second_is_refused(self):
        result = check_paired_selection("second", layouts={"SINGLE"})
        assert result.ok is False
        assert "single" in result.reason.lower()

    def test_first_is_refused(self):
        assert check_paired_selection("first", layouts={"SINGLE"}).ok is False

    def test_both_is_correct(self):
        assert check_paired_selection("both", layouts={"SINGLE"}).ok is True

    def test_the_reason_names_the_fix_not_just_the_fault(self):
        reason = check_paired_selection("second", layouts={"SINGLE"}).reason
        assert "both" in reason


class TestPairedEnd:
    def test_every_selection_is_allowed(self):
        for choice in ("both", "first", "second"):
            assert check_paired_selection(choice, layouts={"PAIRED"}).ok is True

    def test_second_is_the_encode3_case(self):
        """PARP13/GSE290281: crosslink on read 2. Must stay possible."""
        assert check_paired_selection("second", layouts={"PAIRED"}).ok is True


class TestMixedAndDegenerate:
    def test_a_mixed_study_warns_rather_than_silently_picking(self):
        result = check_paired_selection("second", layouts={"SINGLE", "PAIRED"})
        assert result.ok is False
        assert "mixed" in result.reason.lower()

    def test_unknown_layout_does_not_pretend_to_know(self):
        result = check_paired_selection("second", layouts=set())
        assert result.ok is False
        assert "unknown" in result.reason.lower()

    def test_lowercase_layout_values_are_handled(self):
        assert check_paired_selection("both", layouts={"single"}).ok is True

    def test_an_invalid_choice_is_refused(self):
        assert check_paired_selection("read2", layouts={"PAIRED"}).ok is False
