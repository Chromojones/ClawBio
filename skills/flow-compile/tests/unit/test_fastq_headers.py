"""FASTQ header inspection: whether the `rbc:` tag or an underscore barcode is in the read name.
"""

import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.fastq_headers import (
    inspect_header_lines,
)

DEMO_FQ = SKILL_DIR / "demo" / "SRR6181530.fastq.gz"
RBC_HEADER = "@K00102:348:H7GTFBBXY:3:1111:14235:11143:rbc:GGGATAT"
STD_HEADER = "@SRR6181530.1 NS500222:270:HYCM7BGXY:1:11101:11323:1069_CCTCGGATC/1"


class TestHeaderInspection:
    def test_rbc_detected(self):
        has_rbc, has_us = inspect_header_lines([RBC_HEADER])
        assert has_rbc is True
        assert has_us is False

    def test_underscore_barcode_detected(self):
        has_rbc, has_us = inspect_header_lines([STD_HEADER])
        assert has_rbc is False
        assert has_us is True


class TestRbcTagVariants:
    """The `rbc:` tag is not always preceded by a colon.

    GSE297587 (LARP6 iCLIP) writes it straight onto the index field:
        @SRR33628723.1 NS500784:933:...:10741:N:0:1rbc:TAGGATAAA/1
    A `:rbc:` pattern misses that, so the UMI looks absent and the pipeline is told to
    extract it again — stripping 9 bases that were already removed.
    """

    LARP6 = "@SRR33628723.1 NS500784:933:H5W2CBGXN:1:11101:8390:10741:N:0:1rbc:TAGGATAAA/1"
    ENCODE = "@D00611:270:CBQTGANXX:5:1101:1445:2149:rbc:CACTTG 1:N:0:ATCACG"
    ICLIP_END = "@HWI-D00107:170:C4A4KACXX:5:1101:1445:2149:rbc:CACTTG"
    PLAIN = "@SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1"

    def _rec(self, header):
        return [header, "ACGTACGTAC", "+", "IIIIIIIIII"]

    def test_rbc_without_leading_colon_is_detected(self):
        has_rbc, _ = inspect_header_lines(self._rec(self.LARP6))
        assert has_rbc is True

    def test_encode_mid_header_rbc_still_detected(self):
        has_rbc, _ = inspect_header_lines(self._rec(self.ENCODE))
        assert has_rbc is True

    def test_trailing_rbc_still_detected(self):
        has_rbc, _ = inspect_header_lines(self._rec(self.ICLIP_END))
        assert has_rbc is True

    def test_plain_header_has_no_rbc(self):
        has_rbc, _ = inspect_header_lines(self._rec(self.PLAIN))
        assert has_rbc is False

    def test_word_containing_rbc_does_not_false_positive(self):
        """`rbc` must be a tag, not a substring of some other token."""
        has_rbc, _ = inspect_header_lines(self._rec("@read1 sorbc:notatag"))
        assert has_rbc is False
