"""Stage 101's live path — the branch no test had ever executed.

Every other test of this stage supplies `--headers`, so the ENA fetch that `sra-direct-import.md`
calls mandatory was never run by anything. Three defects were sitting in it:

* it imported `preview_headers`, which does not exist in `lib.sra_header_preview` (the module
  defines `preview_run` / `preview_runs`), so the branch died as an ImportError;
* it passed `row["accession"]`, the SRX **experiment**, to a lookup that serves FASTQ per SRR
  **run** — the distinction §0a of the reference states explicitly;
* it classified header *state* only, so `inspection_from_header_records` — the check that
  refuses SRA-direct when the UMI is stranded in the comment — was reachable from no stage at
  all, and the GSE297587 protection existed only as a library function.

The fetch is stubbed here: what is under test is the stage's wiring, not the network.
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


def _stub(monkeypatch, records, source="ena"):
    """Replace the network fetch; record which accessions the stage asked for."""
    asked = []

    def fake_preview_runs(run_accessions, **kwargs):
        asked.extend(run_accessions)
        return ({run: records for run in run_accessions},
                {run: source for run in run_accessions})

    import lib.sra_header_preview as shp

    monkeypatch.setattr(shp, "preview_runs", fake_preview_runs)
    return asked


class TestTheLivePathRuns:
    def test_it_does_not_die_on_a_missing_import(self, routed, monkeypatch):
        """The regression: `from lib.sra_header_preview import preview_headers`."""
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
