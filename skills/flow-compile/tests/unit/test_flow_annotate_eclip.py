"""eCLIP mate selection.

Paired-end eCLIP carries the crosslink on **read 2** (the randomer is trimmed from R2's
5' end and the crosslink sits immediately after it). The Yeo pipeline says so explicitly —
`samtools view -f 128` (second-in-pair) — and `eclipdemux` trims the randomer from
"the front of 2nd read in pair".

seCLIP is genuinely single-end: read 1 is the only read and carries the crosslink.

An earlier version of this module uploaded read 1 for all eCLIP, which analysed the wrong
end of the molecule for every paired-end study.
"""

import sys
from pathlib import Path

import pandas as pd

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.flow_annotate import (  # noqa: E402
    apply_eclip_crosslink_mate_filenames,
    is_eclip_method,
)


class TestIsEclipMethod:
    def test_eclip_and_seclip_recognised(self):
        assert is_eclip_method("eCLIP")
        assert is_eclip_method("seCLIP")

    def test_other_methods_are_not_eclip(self):
        assert not is_eclip_method("iCLIP")
        assert not is_eclip_method("")


class TestCrosslinkMateSelection:
    def test_paired_eclip_promotes_read2_to_the_uploaded_read(self):
        """R2 carries the crosslink — it becomes File, and File 2 is cleared."""
        df = pd.DataFrame(
            [{"File": "SRR1_1.fastq.gz", "File 2": "SRR1_2.fastq.gz",
              "Experimental Method": "eCLIP"}]
        )
        out = apply_eclip_crosslink_mate_filenames(df)
        assert out.loc[0, "File"] == "SRR1_2.fastq.gz"
        assert out.loc[0, "File 2"] == ""

    def test_single_end_eclip_keeps_read1(self):
        """seCLIP / already-R2-only rows have no mate to promote."""
        df = pd.DataFrame(
            [{"File": "SRR1.fastq.gz", "File 2": "", "Experimental Method": "seCLIP"}]
        )
        out = apply_eclip_crosslink_mate_filenames(df)
        assert out.loc[0, "File"] == "SRR1.fastq.gz"
        assert out.loc[0, "File 2"] == ""

    def test_non_eclip_rows_are_untouched(self):
        """iCLIP crosslink is on read 1 — never promote its mate."""
        df = pd.DataFrame(
            [{"File": "SRR1_1.fastq.gz", "File 2": "SRR1_2.fastq.gz",
              "Experimental Method": "iCLIP"}]
        )
        out = apply_eclip_crosslink_mate_filenames(df)
        assert out.loc[0, "File"] == "SRR1_1.fastq.gz"
        assert out.loc[0, "File 2"] == "SRR1_2.fastq.gz"

    def test_mixed_table_only_promotes_eclip_rows(self):
        df = pd.DataFrame(
            [
                {"File": "a_1.fastq.gz", "File 2": "a_2.fastq.gz",
                 "Experimental Method": "eCLIP"},
                {"File": "b_1.fastq.gz", "File 2": "b_2.fastq.gz",
                 "Experimental Method": "iCLIP"},
            ]
        )
        out = apply_eclip_crosslink_mate_filenames(df)
        assert out.loc[0, "File"] == "a_2.fastq.gz"
        assert out.loc[1, "File"] == "b_1.fastq.gz"

    def test_missing_file2_column_is_safe(self):
        df = pd.DataFrame([{"File": "SRR1.fastq.gz", "Experimental Method": "eCLIP"}])
        out = apply_eclip_crosslink_mate_filenames(df)
        assert out.loc[0, "File"] == "SRR1.fastq.gz"
