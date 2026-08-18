"""`paired=first`/`second` on SINGLE-end data produces an empty samplesheet.

GSE75418 and GSE68800 are both single-end. Both were submitted with `paired="second"` —
inherited from a submit script copied out of GSE113638, whose default suits the paired-end
eCLIP it was written for. The pipeline emitted rows with both read columns blank::

    MSI1_U251_Hs_WT_rep3_SRX1023997,1,,
    SAFB1_SHSY5Y_Hs_heatshock_rep6_SRX1473616,1,,

and died at `SAMPLE_BASE_SAMPLESHEET_CHECK` with::

    ERROR: Please check samplesheet -> Invalid number of populated columns (minimum = 3)!

That message never mentions reads, mates or `paired`, so it reads as a malformed sheet rather
than an impossible mate selection. Both executions had to be deleted and resubmitted.

The layout is knowable before submitting — ENA's `library_layout` says SINGLE or PAIRED — so
this is checkable up front rather than ~40 s into a run.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.paired_selection import check_paired_selection  # noqa: E402


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
