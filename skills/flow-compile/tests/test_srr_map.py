"""srr_map integrity and mate pairing.

`srr_map.tsv` is agent-authored, so nothing downstream can tell a transposed row from a
correct one — a wrong GSM↔SRR pairing silently attaches the wrong reads to a sample. And
the mate lookup used to take "the second row" as read 2, which for a single-end GSM with
two runs declares two *unrelated* accessions to be a pair.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.flow_annotate import _fastq_paths_for_gsm, validate_srr_map  # noqa: E402


def _rows(records):
    return pd.DataFrame(records)


class TestMatePairing:
    def test_true_paired_run_pairs_both_mates(self):
        rows = _rows(
            [
                {"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1_1.fastq.gz"},
                {"gsm": "GSM1", "srr": "SRR1", "mate": 2, "fastq": "SRR1_2.fastq.gz"},
            ]
        )
        assert _fastq_paths_for_gsm(rows) == ("SRR1_1.fastq.gz", "SRR1_2.fastq.gz")

    def test_single_end_gsm_with_two_runs_does_not_fabricate_a_mate(self):
        """Two runs of a single-end GSM are separate runs, not a pair."""
        rows = _rows(
            [
                {"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1.fastq.gz"},
                {"gsm": "GSM1", "srr": "SRR2", "mate": 1, "fastq": "SRR2.fastq.gz"},
            ]
        )
        file1, file2 = _fastq_paths_for_gsm(rows)
        assert file1 == "SRR1.fastq.gz"
        assert file2 == ""

    def test_single_end_single_run_has_no_mate(self):
        rows = _rows([{"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1.fastq.gz"}])
        assert _fastq_paths_for_gsm(rows) == ("SRR1.fastq.gz", "")

    def test_explicit_file2_column_wins(self):
        rows = _rows(
            [
                {
                    "gsm": "GSM1", "srr": "SRR1", "mate": 1,
                    "fastq": "a_1.fastq.gz", "file2": "a_2.fastq.gz",
                }
            ]
        )
        assert _fastq_paths_for_gsm(rows) == ("a_1.fastq.gz", "a_2.fastq.gz")


class TestValidateSrrMap:
    def test_clean_map_has_no_issues(self):
        rows = _rows(
            [
                {"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1_1.fastq.gz"},
                {"gsm": "GSM1", "srr": "SRR1", "mate": 2, "fastq": "SRR1_2.fastq.gz"},
                {"gsm": "GSM2", "srr": "SRR2", "mate": 1, "fastq": "SRR2.fastq.gz"},
            ]
        )
        assert validate_srr_map(rows) == []

    def test_run_shared_between_two_gsms_is_an_error(self):
        """The signature of a transposed or copy-pasted row."""
        rows = _rows(
            [
                {"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1.fastq.gz"},
                {"gsm": "GSM2", "srr": "SRR1", "mate": 1, "fastq": "SRR1.fastq.gz"},
            ]
        )
        issues = validate_srr_map(rows)
        assert any("SRR1" in i and "GSM1" in i and "GSM2" in i for i in issues)

    def test_duplicate_gsm_srr_mate_is_an_error(self):
        rows = _rows(
            [
                {"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1.fastq.gz"},
                {"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1.fastq.gz"},
            ]
        )
        assert any("duplicate" in i.lower() for i in validate_srr_map(rows))

    def test_bad_mate_value_is_an_error(self):
        rows = _rows([{"gsm": "GSM1", "srr": "SRR1", "mate": 3, "fastq": "x.fastq.gz"}])
        assert any("mate" in i.lower() for i in validate_srr_map(rows))

    def test_multi_run_gsm_is_reported_because_extra_runs_are_dropped(self):
        rows = _rows(
            [
                {"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": "SRR1.fastq.gz"},
                {"gsm": "GSM1", "srr": "SRR2", "mate": 1, "fastq": "SRR2.fastq.gz"},
            ]
        )
        assert any("multiple runs" in i.lower() for i in validate_srr_map(rows))

    def test_empty_fastq_is_an_error(self):
        rows = _rows([{"gsm": "GSM1", "srr": "SRR1", "mate": 1, "fastq": ""}])
        assert any("fastq" in i.lower() for i in validate_srr_map(rows))
