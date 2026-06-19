"""Tests for FASTQ header inspection and pipeline params."""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
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
