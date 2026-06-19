"""Tests for header cleaning stage."""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.header_clean import (
    cleaned_fastq_name,
    headers_need_cleaning,
    resolve_removespace_script,
    write_clean_fastq_script,
)

GSE_HEADER = "@SRR6181530.1 NS500222:270:HYCM7BGXY:1:11101:11323:1069_CCTCGGATC/1"
STD_HEADER = "@SRR34631059.1 NB501946:305:HYHWNBGX9:1:11101:4877:1073 length=92"


class TestHeaderClean:
    def test_gse_header_needs_cleaning(self):
        assert headers_need_cleaning([GSE_HEADER]) is True

    def test_illumina_header_with_spaces_needs_cleaning(self):
        assert headers_need_cleaning([STD_HEADER]) is True

    def test_cleaned_name(self):
        assert cleaned_fastq_name(Path("SRR6181530.fastq.gz")) == "SRR6181530.cleaned.fastq.gz"

    def test_resolve_removespace_advbfx(self):
        path = resolve_removespace_script()
        assert path is not None
        assert path.name == "removespace.py"

    def test_write_clean_script(self, tmp_path):
        rs = resolve_removespace_script()
        fq = tmp_path / "SRR6181530.fastq.gz"
        fq.touch()
        script = write_clean_fastq_script(tmp_path, [fq], removespace_script=rs)
        assert script is not None
        text = script.read_text()
        assert "removespace" in text
        assert "SRR6181530.cleaned.fastq.gz" in text
