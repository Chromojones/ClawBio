"""Tests for FASTQ header inspection and pipeline params."""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.fastq_headers import (
    inspect_header_lines,
    sample_headers_from_fastq_dir,
    sample_read_headers,
)
from lib.pipeline_params import derive_clip_pipeline_params

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

    def test_demo_fastq_sample(self):
        if not DEMO_FQ.exists():
            pytest.skip("demo FASTQ not present")
        headers = sample_read_headers(DEMO_FQ, n_reads=3)
        assert len(headers) == 12  # 4 lines x 3 reads
        assert headers[0].startswith("@SRR6181530")

    def test_demo_inspection_no_rbc(self):
        if not DEMO_FQ.exists():
            pytest.skip("demo FASTQ not present")
        inspection = sample_headers_from_fastq_dir([("SRR6181530", DEMO_FQ)], reads_per_file=3)
        assert inspection.has_rbc is False
        assert inspection.barcode_in_header is True


class TestPipelineParams:
    def test_rbc_false_move(self):
        from lib.fastq_headers import HeaderInspection

        insp = HeaderInspection(has_rbc=True, barcode_in_header=True, sample_headers=[], fastq_files=[])
        params = derive_clip_pipeline_params(insp, five_prime_barcode="NNNCGGANNN")
        assert params["move_umi_to_header"] == "false"
        assert params["umi_separator"] == "rbc:"
        assert "umi_header_format" not in params

    def test_underscore_extract(self):
        from lib.fastq_headers import HeaderInspection

        insp = HeaderInspection(has_rbc=False, barcode_in_header=True, sample_headers=[], fastq_files=[])
        params = derive_clip_pipeline_params(insp, five_prime_barcode="NNNCGGANNN")
        assert params["move_umi_to_header"] == "true"
        assert params["umi_separator"] == "_"
        assert params["umi_header_format"] == "NNNNNNNNNN"

    def test_no_header_inspection_defaults_extract(self):
        params = derive_clip_pipeline_params(None, five_prime_barcode="NNNNNNNNNNNNNNN")
        assert params["move_umi_to_header"] == "true"
        assert params["umi_separator"] == "_"
        assert params["encode_eclip"] == "false"

    def test_eclip_raw_sra_encode_false(self):
        from lib.fastq_headers import HeaderInspection

        insp = HeaderInspection(has_rbc=False, barcode_in_header=False, sample_headers=[], fastq_files=[])
        params = derive_clip_pipeline_params(
            insp, five_prime_barcode="NNNNNNNNNN", experimental_method="eCLIP"
        )
        assert params["move_umi_to_header"] == "true"
        assert params["encode_eclip"] == "false"
        assert params["umi_header_format"] == "NNNNNNNNNN"

    def test_eclip_rbc_in_header_encode_true(self):
        from lib.fastq_headers import HeaderInspection

        insp = HeaderInspection(has_rbc=True, barcode_in_header=True, sample_headers=[], fastq_files=[])
        params = derive_clip_pipeline_params(
            insp, five_prime_barcode="NNNNNNNNNN", experimental_method="eCLIP"
        )
        assert params["move_umi_to_header"] == "false"
        assert params["umi_separator"] == "rbc:"
        assert params["encode_eclip"] == "true"

    def test_iclip_rbc_encode_false(self):
        from lib.fastq_headers import HeaderInspection

        insp = HeaderInspection(has_rbc=True, barcode_in_header=True, sample_headers=[], fastq_files=[])
        params = derive_clip_pipeline_params(
            insp, five_prime_barcode="NNNNNNNNNNNNNNN", experimental_method="iCLIP"
        )
        assert params["encode_eclip"] == "false"


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
