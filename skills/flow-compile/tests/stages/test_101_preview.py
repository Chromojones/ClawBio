"""Stage 101's live path, with the ENA fetch stubbed.

Checks the wiring: the stage asks for each SRR run (ENA serves FASTQ per run, not per SRX), and
the UMI-in-comment refusal fires at the stage, not only in the library.

Story: FAILURES.md#defline-provenance
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402

PY = sys.executable

#: The real ENA rendering: accession prefix, original header pushed into the comment.
UMI_IN_COMMENT = [
    "@SRR33628723.1 NS500784:933:H5W2CBGXN:1:11101:8390:10741:N:0:1rbc:TAGGATAAA/1",
    "NAGCAATGGCGCG", "+", "#AAFFJJJ",
]
#: `fastq-dump --origfmt`: the same UMI, no comment field to find it in.
UMI_IN_NAME_FROM_FALLBACK = [
    "@NS500784:933:H5W2CBGXN:1:11101:8390:10741:N:0:1rbc:TAGGATAAA",
    "NAGCAATGGCGCG", "+", "#AAFFJJJ",
]
CLEAN = [
    "@SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1",
    "NAGCAATGGCGCG", "+", "#AAFFJJJ",
]


def _stage_module():
    spec = importlib.util.spec_from_file_location(
        "stage_101", SKILL_DIR / "stages" / "101_preview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def routed(tmp_path):
    """A run parked on the direct line with one indexed sample."""
    out = tmp_path / "run"
    out.mkdir()
    st.record(out, "06_route", st.OK)
    st.set_route(out, line="direct", protocol="iCLIP", reason="test")
    (out / "sheet_rows.json").write_text(json.dumps(
        [{"accession": "SRX3300000", "srr": "SRR33628723", "gsm": "GSM1",
          "sample_type": "CLIP"}]) + "\n")
    return out


def _stub(monkeypatch, records, source="ena", load_format="FASTQ"):
    """Replace the network fetch; record which accessions the stage asked for."""
    asked = []

    def fake_preview_runs(run_accessions, **kwargs):
        asked.extend(run_accessions)
        return ({run: (records[run] if isinstance(records, dict) else records)
                 for run in run_accessions},
                {run: source for run in run_accessions})

    import lib.sra_header_preview as shp

    monkeypatch.setattr(shp, "preview_runs", fake_preview_runs)
    monkeypatch.setattr(shp, "sra_load_format", lambda run: load_format)
    return asked


def _records(seqs, prefix="SRR1"):
    """Four-line FASTQ records in ENA's rendering."""
    out = []
    for i, s in enumerate(seqs, 1):
        out += [f"@{prefix}.{i} {i}/1", s, "+", "F" * len(s)]
    return out


def _untrimmed(n=300, seed=1):
    import random

    rng = random.Random(seed)
    reads = []
    for _ in range(n):
        head = "".join(rng.choices("ACGT", weights=[2, 2, 2, 4], k=8)) \
            + "".join(rng.choice("AT") for _ in range(2)) + "T"
        # genomic-like: 12-20% off even, never uniform
        insert = "".join(rng.choices("ACGT", weights=[3, 1, 1, 3], k=rng.randint(10, 30)))
        reads.append((head + insert + "AGATCGGAAGAGCACACGTCTGAACTCCAGTCACATCACG")[:50])
    return reads


def _processed(n=300, seed=2):
    import random

    rng = random.Random(seed)
    return ["".join(rng.choices("ACGT", k=rng.randint(15, 59))) for _ in range(n)]


class TestTheLivePathRuns:
    def test_it_does_not_die_on_a_missing_import(self, routed, monkeypatch):
        """The live branch imports only names `lib.sra_header_preview` defines."""
        _stub(monkeypatch, CLEAN)
        code = _stage_module().main(["--output", str(routed)])
        assert code == 0
        assert st.study(routed)["header_state"] == "raw"

    def test_it_asks_for_the_run_not_the_experiment(self, routed, monkeypatch):
        """ENA serves FASTQ per SRR; an SRX resolves to no files and the preview goes blind."""
        asked = _stub(monkeypatch, CLEAN)
        _stage_module().main(["--output", str(routed)])
        assert asked == ["SRR33628723"], asked

    def test_a_row_without_a_run_accession_is_refused(self, routed, monkeypatch, capsys):
        """Silently previewing nothing would record a header state derived from no headers."""
        _stub(monkeypatch, CLEAN)
        (routed / "sheet_rows.json").write_text(json.dumps(
            [{"accession": "SRX3300000", "gsm": "GSM1"}]) + "\n")
        assert _stage_module().main(["--output", str(routed)]) == 4
        assert "srr" in capsys.readouterr().err.lower()


class TestTheCommentRefusalFiresAtTheStage:
    def test_a_umi_in_the_comment_stops_the_run(self, routed, monkeypatch, capsys):
        """GSE297587: aligners drop the comment, so dedup dies after mapping. Refuse here."""
        _stub(monkeypatch, UMI_IN_COMMENT)
        code = _stage_module().main(["--output", str(routed)])
        assert code == 4
        assert "comment" in capsys.readouterr().err.lower()

    def test_the_fallback_source_cannot_clear_it(self, routed, monkeypatch, capsys):
        """`--origfmt` deletes the comment field; provenance keeps the verdict honest."""
        _stub(monkeypatch, UMI_IN_NAME_FROM_FALLBACK, source="fastq-dump")
        assert _stage_module().main(["--output", str(routed)]) == 4
        assert "comment" in capsys.readouterr().err.lower()

    def test_a_clean_study_is_not_blocked(self, routed, monkeypatch):
        _stub(monkeypatch, CLEAN)
        assert _stage_module().main(["--output", str(routed)]) == 0


class TestTheIndexCarriesTheRun:
    """101 can only ask for the SRR if 02_index recorded it beside the SRX."""

    def test_sheet_rows_carry_both_accessions(self, tmp_path):
        out = tmp_path / "idx"
        out.mkdir()
        srr_map = tmp_path / "srr_map.tsv"
        srr_map.write_text("gsm\tsrx\tsrr\nGSM2817677\tSRX3300000\tSRR6181530\n")
        st.record(out, "00_setup", st.OK)
        st.record(out, "01_study", st.OK)
        proc = subprocess.run(
            [PY, str(SKILL_DIR / "stages" / "02_index.py"), "--output", str(out),
             "--geo-matrix", str(SKILL_DIR / "demo" / "GSE105082_series_matrix.txt"),
             "--srr-map", str(srr_map)],
            capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=120)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rows = json.loads((out / "sheet_rows.json").read_text())
        assert rows[0]["accession"] == "SRX3300000"
        assert rows[0]["srr"] == "SRR6181530"


class TestTheReadStructureIsRecorded:
    """101 records whether the reads are untrimmed or processed, for 108 to act on."""

    def test_untrimmed_reads_are_recorded_with_their_block(self, routed, monkeypatch):
        _stub(monkeypatch, _records(_untrimmed()))
        assert _stage_module().main(["--output", str(routed)]) == 0
        assert st.study(routed)["read_structure"] == "untrimmed"
        recorded = json.loads((routed / "read_structure.json").read_text())["SRR33628723"]
        assert recorded["verdict"] == "untrimmed"
        assert recorded["block_len_min"] == 11

    def test_processed_reads_are_recorded(self, routed, monkeypatch, capsys):
        """SRR5646571: varied lengths, no adapter, loaded from a BAM."""
        _stub(monkeypatch, _records(_processed()), load_format="BAM")
        assert _stage_module().main(["--output", str(routed)]) == 0
        assert st.study(routed)["read_structure"] == "processed"
        assert "processed" in capsys.readouterr().out.lower()

    def test_runs_that_disagree_are_refused(self, routed, monkeypatch, capsys):
        (routed / "sheet_rows.json").write_text(json.dumps([
            {"accession": "SRX1", "srr": "SRR1", "gsm": "GSM1", "sample_type": "CLIP"},
            {"accession": "SRX2", "srr": "SRR2", "gsm": "GSM2", "sample_type": "CLIP"},
        ]) + "\n")
        _stub(monkeypatch, {"SRR1": _records(_untrimmed(), "SRR1"),
                            "SRR2": _records(_processed(), "SRR2")})
        assert _stage_module().main(["--output", str(routed)]) == 4
        assert "untrimmed" in capsys.readouterr().err.lower()


class TestOnlyHeaderLinesAreClassified:
    """Sequence and quality lines are not headers; classifying them as `raw` made every
    non-raw study read as mixed. ENA's accession prefix must not hide the state either."""

    def test_a_prepended_randomer_study_is_not_refused_as_mixed(self, routed, monkeypatch):
        recs = []
        for i in range(6):
            recs += [f"@SRR33628723.{i+1} TAAAG:HWI-D00611:119:C6VM5ANXX:1:1101:{i}:90397 2:N:0:TCCGG",
                     "ACGTACGTACGTACGT", "+", "FFFFFFFFFFFFFFFF"]
        _stub(monkeypatch, recs)
        assert _stage_module().main(["--output", str(routed)]) == 0
        assert st.study(routed)["header_state"] == "randomer_prefix"
