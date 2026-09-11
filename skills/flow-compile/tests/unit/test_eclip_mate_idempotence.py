"""`apply_eclip_crosslink_mate_filenames` is idempotent, and exactly one stage calls it.

It promotes `File 2` to `File` for paired eCLIP and blanks `File 2`; a second pass is a no-op
only because the blank `File 2` skips the promotion.

Story: FAILURES.md#eclip-mate-filenames
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

pd = pytest.importorskip("pandas")

from lib.flow_annotate import apply_eclip_crosslink_mate_filenames as apply_mates  # noqa: E402


def _paired_eclip():
    """A row where read 2 is the crosslink mate and has NOT yet been promoted."""
    return pd.DataFrame([
        {"Sample Name": "IP1", "File": "SRR1_1.fastq.gz", "File 2": "SRR1_2.fastq.gz",
         "Experimental Method": "eCLIP"},
        {"Sample Name": "IP2", "File": "SRR2_1.fastq.gz", "File 2": "SRR2_2.fastq.gz",
         "Experimental Method": "eCLIP"},
    ])


class TestTheFirstCallActuallyDoesSomething:
    """Without this, the idempotence test below proves nothing."""

    def test_read_two_is_promoted(self):
        out = apply_mates(_paired_eclip())
        assert list(out["File"]) == ["SRR1_2.fastq.gz", "SRR2_2.fastq.gz"]

    def test_the_second_mate_is_cleared(self):
        assert list(apply_mates(_paired_eclip())["File 2"]) == ["", ""]


class TestIdempotence:
    def test_twice_equals_once(self):
        once = apply_mates(_paired_eclip())
        twice = apply_mates(apply_mates(_paired_eclip()))
        assert list(once["File"]) == list(twice["File"])
        assert list(once["File 2"]) == list(twice["File 2"])

    def test_three_times_too(self):
        once = apply_mates(_paired_eclip())
        thrice = apply_mates(apply_mates(apply_mates(_paired_eclip())))
        assert list(once["File"]) == list(thrice["File"])


class TestWhatItLeavesAlone:
    def test_iclip_rows_are_untouched(self):
        """iCLIP carries its crosslink on read 1; promoting read 2 would be wrong."""
        df = pd.DataFrame([{"Sample Name": "S1", "File": "SRR1_1.fastq.gz",
                            "File 2": "SRR1_2.fastq.gz", "Experimental Method": "iCLIP"}])
        out = apply_mates(df)
        assert out.loc[0, "File"] == "SRR1_1.fastq.gz"
        assert out.loc[0, "File 2"] == "SRR1_2.fastq.gz"

    def test_single_end_seclip_has_nothing_to_promote(self):
        """seCLIP is genuinely single-end: read 1 already carries the crosslink."""
        df = pd.DataFrame([{"Sample Name": "S1", "File": "SRR1.fastq.gz", "File 2": "",
                            "Experimental Method": "seCLIP"}])
        assert apply_mates(df).loc[0, "File"] == "SRR1.fastq.gz"

    def test_a_table_without_a_second_mate_column_is_returned_unchanged(self):
        df = pd.DataFrame([{"Sample Name": "S1", "File": "SRR1.fastq.gz",
                            "Experimental Method": "eCLIP"}])
        assert apply_mates(df).loc[0, "File"] == "SRR1.fastq.gz"


class TestItIsActuallyWiredIn:
    """A stage calls it; otherwise paired eCLIP uploads read 1, the barcode-only mate."""

    def test_a_stage_promotes_the_crosslink_mate(self):
        from pathlib import Path

        stages = Path(__file__).resolve().parent.parent / "stages"
        callers = [
            p.name for p in stages.glob("*.py")
            if "apply_eclip_crosslink_mate_filenames" in p.read_text()
        ]
        assert callers, "no stage promotes the eCLIP crosslink mate"

    def test_exactly_one_stage_does(self):
        """Two writers of the File column would make the annotation stale."""
        from pathlib import Path

        stages = Path(__file__).resolve().parent.parent / "stages"
        callers = [
            p.name for p in stages.glob("*.py")
            if "apply_eclip_crosslink_mate_filenames(" in p.read_text()
        ]
        assert len(callers) == 1, f"promoted in {callers}"
