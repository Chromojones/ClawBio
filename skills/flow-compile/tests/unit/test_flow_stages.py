"""Tests for upload/analysis script generation."""

import sys
from pathlib import Path

import pandas as pd

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.flow_stages import (
    sample_name_filter_from_annotation,
    write_analysis_script,
)


def test_sample_name_filter():
    df = pd.DataFrame({"File": ["SRR6181530.cleaned.fastq.gz", "SRR6181534.cleaned.fastq.gz"]})
    assert sample_name_filter_from_annotation(df) == "SRR6181530|SRR6181534"


def test_write_analysis_script(tmp_path):
    an = SKILL_DIR / "lib/vendor/flow_api/analysis/flowrunanalysis_flowbio.py"
    write_analysis_script(
        tmp_path,
        analysis_script=an,
        project_id="123",
        pipeline_params={"umi_header_format": "NNNNNNNNNN", "move_umi_to_header": "true", "umi_separator": "_"},
        sample_name_filter="SRR1",
        experimental_method="iCLIP",
    )
    assert (tmp_path / "run_analysis.sh").exists()
    assert "--params-json" in (tmp_path / "run_analysis.sh").read_text()
