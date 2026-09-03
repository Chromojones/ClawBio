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

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
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


class TestLoadRequiresOnlyWhatItUses:
    """GSE262435: a map built to the documented direct-line schema (`gsm`, `srr`, `srx`)
    died with `SRR map must contain columns: ['fastq', 'gsm', 'mate', 'srr']`.

    The required set was inverted relative to the SRA-direct line's real needs. `fastq` is
    never read on that line — `build_import_sheet` maps annotation to an accession plus
    metadata and never touches the File column — so requiring it forces the operator to
    invent filenames nothing downloads. Meanwhile `srx`, which 109_sheet hard-refuses a run
    accession over, was not required at all.

    So: `gsm` and `srr` are the map. `mate` defaults to 1 and `fastq` is derived on ENA's
    own naming convention when the column is absent; supply either and you own it.
    """

    def _write(self, tmp_path, text):
        path = tmp_path / "srr_map.tsv"
        path.write_text(text)
        return path

    def test_the_documented_direct_line_schema_loads(self, tmp_path):
        from lib.flow_annotate import load_srr_map

        path = self._write(tmp_path, "gsm\tsrx\tsrr\nGSM1\tSRX1\tSRR1\n")
        frame = load_srr_map(path)
        assert list(frame["gsm"]) == ["GSM1"]
        assert list(frame["srx"]) == ["SRX1"]

    def test_a_missing_mate_defaults_to_one(self, tmp_path):
        from lib.flow_annotate import load_srr_map

        frame = load_srr_map(self._write(tmp_path, "gsm\tsrr\nGSM1\tSRR1\n"))
        assert list(frame["mate"]) == [1]

    def test_a_missing_fastq_is_derived_on_the_ena_convention(self, tmp_path):
        from lib.flow_annotate import load_srr_map

        frame = load_srr_map(self._write(tmp_path, "gsm\tsrr\nGSM1\tSRR1\n"))
        assert list(frame["fastq"]) == ["SRR1.fastq.gz"]

    def test_a_derived_fastq_is_mate_aware(self, tmp_path):
        """ENA serves a paired run as SRR1_1/SRR1_2, so a supplied mate must be honoured."""
        from lib.flow_annotate import load_srr_map

        frame = load_srr_map(self._write(
            tmp_path, "gsm\tsrr\tmate\nGSM1\tSRR1\t1\nGSM1\tSRR1\t2\n"))
        assert list(frame["fastq"]) == ["SRR1_1.fastq.gz", "SRR1_2.fastq.gz"]

    def test_a_supplied_fastq_is_never_overwritten(self, tmp_path):
        from lib.flow_annotate import load_srr_map

        frame = load_srr_map(self._write(
            tmp_path, "gsm\tsrr\tmate\tfastq\nGSM1\tSRR1\t1\tcustom_name.fq.gz\n"))
        assert list(frame["fastq"]) == ["custom_name.fq.gz"]

    def test_a_supplied_but_empty_fastq_still_refuses(self, tmp_path):
        """Deriving is for an ABSENT column. A blank cell in a supplied column is a mistake."""
        from lib.flow_annotate import load_srr_map

        path = self._write(tmp_path, "gsm\tsrr\tmate\tfastq\nGSM1\tSRR1\t1\t\n")
        with pytest.raises(ValueError, match="fastq"):
            load_srr_map(path)

    def test_the_map_still_needs_a_gsm_and_a_run(self, tmp_path):
        from lib.flow_annotate import load_srr_map

        with pytest.raises(ValueError, match="srr"):
            load_srr_map(self._write(tmp_path, "gsm\tsrx\nGSM1\tSRX1\n"))

    def test_the_integrity_checks_still_block(self, tmp_path):
        """Relaxing the columns must not relax the transposed-row guard."""
        from lib.flow_annotate import load_srr_map

        path = self._write(tmp_path, "gsm\tsrr\nGSM1\tSRR1\nGSM2\tSRR1\n")
        with pytest.raises(ValueError, match="integrity"):
            load_srr_map(path)

    def test_the_local_line_demo_map_is_unaffected(self, tmp_path):
        """The bundled map supplies mate and fastq; it must load exactly as before."""
        from lib.flow_annotate import load_srr_map

        frame = load_srr_map(SKILL_DIR / "demo_gse105082_srr_map.tsv")
        assert list(frame["fastq"]) == ["SRR6181530.fastq.gz"]
