"""Tests for uvCLAP UMI extraction helpers."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.pipeline_params import UVCLAP_TRIMGALORE_PARAMS, derive_uvclap_post_umi_params
from lib.uvclap_umi_extract import (
    UVCLAP_BC_PATTERN,
    UVCLAP_BC_PATTERN2,
    apply_uvclap_umi_filenames,
    umi_output_basename,
    write_merge_pe_script,
    write_umi_extract_script,
)


class TestUvclapUmiExtract:
    def test_bc_pattern_lengths(self):
        assert len(UVCLAP_BC_PATTERN) == 10
        assert len(UVCLAP_BC_PATTERN2) == 5

    def test_apply_uvclap_filenames_keeps_pe(self):
        df = pd.DataFrame(
            {
                "File": ["SRR3997079_1.fastq.gz"],
                "File 2": ["SRR3997079_2.fastq.gz"],
            }
        )
        out = apply_uvclap_umi_filenames(df)
        assert out.iloc[0]["File"] == umi_output_basename("SRR3997079", 1)
        assert out.iloc[0]["File 2"] == umi_output_basename("SRR3997079", 2)

    def test_write_umi_extract_script(self, tmp_path):
        fq = tmp_path / "fastq"
        fq.mkdir()
        r1 = fq / "SRR1_1.fastq.gz"
        r2 = fq / "SRR1_2.fastq.gz"
        r1.write_bytes(b"x")
        r2.write_bytes(b"x")
        script = write_umi_extract_script(tmp_path, [("SRR1", r1, r2)])
        assert script and script.exists()
        text = script.read_text()
        assert '"$UMI_TOOLS" extract' in text
        assert UVCLAP_BC_PATTERN in text
        assert UVCLAP_BC_PATTERN2 in text
        assert "read2-out" in text
        assert "PARALLEL_JOBS" in text

    def test_write_merge_pe_script(self, tmp_path):
        fq = tmp_path / "fastq"
        fq.mkdir()
        script = write_merge_pe_script(
            tmp_path,
            [("GSM2258634", ["SRR3997079", "SRR3997080"])],
            fastq_dir=fq,
        )
        assert script and script.exists()
        text = script.read_text()
        assert "GSM2258634_1.umi.fastq.gz" in text
        assert "SRR3997079_1.umi.fastq.gz" in text

    def test_derive_uvclap_post_umi_params(self):
        params = derive_uvclap_post_umi_params()
        assert params["move_umi_to_header"] == "false"
        assert params["umi_separator"] == "_"
        assert "three_prime_clip_R1 10" in params["trimgalore_params"]
        assert params["trimgalore_params"] == UVCLAP_TRIMGALORE_PARAMS
