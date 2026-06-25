"""Tests for FLASH UMI extraction helpers."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.flash_umi_extract import (
    FLASH_BC_PATTERN2,
    apply_umi_extracted_filenames,
    planned_flash_umi_pairs,
    umi_output_basename,
    write_umi_extract_script,
)


class TestFlashUmiExtract:
    def test_bc_pattern_length(self):
        assert len(FLASH_BC_PATTERN2) == 13

    def test_apply_umi_filenames_clears_file2(self):
        df = pd.DataFrame(
            {
                "File": ["SRR4473871_1.cleaned.fastq.gz"],
                "File 2": ["SRR4473871_2.fastq.gz"],
            }
        )
        out = apply_umi_extracted_filenames(df)
        assert out.iloc[0]["File"] == umi_output_basename("SRR4473871")
        assert out.iloc[0]["File 2"] == ""

    def test_write_umi_extract_script(self, tmp_path):
        fq = tmp_path / "fastq"
        fq.mkdir()
        r1 = fq / "SRR1_1.cleaned.fastq.gz"
        r2 = fq / "SRR1_2.fastq.gz"
        r1.write_bytes(b"x")
        r2.write_bytes(b"x")
        script = write_umi_extract_script(tmp_path, [("SRR1", r1, r2)])
        assert script and script.exists()
        text = script.read_text()
        assert "umi_tools extract" in text
        assert "NNXXXXXXNNNNN" in text
        assert "SRR1_1.umi.fastq.gz" in text
        assert "PARALLEL_JOBS" in text
        assert "extract_one()" in text

    def test_planned_pairs_prefers_cleaned(self, tmp_path):
        pairs = planned_flash_umi_pairs(tmp_path, ["SRR9"], prefer_cleaned_r1=True)
        assert pairs[0][1].name == "SRR9_1.cleaned.fastq.gz"
