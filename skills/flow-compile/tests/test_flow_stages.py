"""Tests for upload/analysis script generation."""

import sys
from pathlib import Path

import pandas as pd

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.flow_stages import (
    sample_name_filter_from_annotation,
    write_analysis_script,
    write_upload_script,
)


def test_sample_name_filter():
    df = pd.DataFrame({"File": ["SRR6181530.cleaned.fastq.gz", "SRR6181534.cleaned.fastq.gz"]})
    assert sample_name_filter_from_annotation(df) == "SRR6181530|SRR6181534"


def test_write_scripts(tmp_path):
    ann = tmp_path / "annotation.csv"
    pd.DataFrame({"File": ["SRR1.fastq.gz"], "Sample Name": ["test"], "Experimental Method": ["iCLIP"]}).to_csv(
        ann, index=False
    )
    up = Path("/home/mikej10/advbfx/flowAPIscripts/upload/uploadsample_flowbio_v6.py")
    an = Path("/home/mikej10/advbfx/flowAPIscripts/analysis/flowrunanalysis_flowbio.py")
    if not up.is_file() or not an.is_file():
        return
    write_upload_script(
        tmp_path,
        upload_script=up,
        annotation_path=ann,
        project_id="123",
        base_dir=tmp_path,
        row_count=1,
    )
    write_analysis_script(
        tmp_path,
        analysis_script=an,
        project_id="123",
        pipeline_params={"umi_header_format": "NNNNNNNNNN", "move_umi_to_header": "true", "umi_separator": "_"},
        sample_name_filter="SRR1",
        experimental_method="iCLIP",
    )
    assert (tmp_path / "upload.sh").exists()
    assert '--input "$ANNOTATION"' in (tmp_path / "upload.sh").read_text()
    assert (tmp_path / "run_analysis.sh").exists()
    assert "--params-json" in (tmp_path / "run_analysis.sh").read_text()
