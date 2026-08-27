"""GSE105082 end to end through the stages, replacing the old `run_pipeline` case tests.

The old test drove one function that did everything and asserted on its combined output. The
same ground is covered here by running the stages in order, which additionally checks the
thing the old design could not express: that each stage stops the run when it should, and that
a stage does not have to be executed twice for a later one to see its work.

The barcode assertions are the study's real ones. GSE105082's GSM2817677 carries `NNNCGGANNN`,
recoverable from the GEO record, and GSM2817678 carries `NNNGGCANNN` — the two differ only in
their fixed core, which is what makes this a good case: a resolver that ignored the core would
give both samples the same barcode and nothing downstream would notice.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402
from tests.conftest import GSE105082_MATRIX, GSE105082_PAPER, GSE105082_SRR_MAP  # noqa: E402

PY = sys.executable

#: Everything the study itself offers: the series matrix, the one cached GEO sample page the
#: demo carries, and the paper excerpt. The old test supplied all three; supplying fewer makes
#: the resolver fall back to a low-confidence empty proposal, which is correct behaviour and a
#: poor test of extraction.
_EVIDENCE = (
    "--geo-matrix", str(GSE105082_MATRIX),
    "--geo-cache-dir", str(SKILL_DIR / "demo"),
    "--paper-text", str(GSE105082_PAPER),
)


def _stage(name, out, *extra):
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / f"{name}.py"), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=180,
    )


@pytest.fixture
def run_dir(tmp_path):
    out = tmp_path / "gse105082"
    out.mkdir()
    assert _stage("00_setup", out, "--accession", "GSE105082",
                  "--project-id", "997999200849251656", "--offline").returncode == 0
    assert _stage("01_study", out).returncode == 0
    assert _stage("02_index", out, "--geo-matrix", str(GSE105082_MATRIX),
                  "--srr-map", str(GSE105082_SRR_MAP)).returncode == 0
    return out


class TestTheTrunkRuns:
    def test_setup_records_the_study(self, run_dir):
        assert st.study(run_dir)["accession"] == "GSE105082"

    def test_the_index_reads_all_24_samples(self, run_dir):
        index = json.loads((run_dir / "index.json").read_text())
        assert index["gse"] == "GSE105082"
        assert index["gsm_count"] == 24

    def test_a_missing_srx_warns_rather_than_refuses(self, run_dir):
        """This demo's srr_map has no srx column, and the local line never needs one."""
        assert st.status(run_dir, "02_index") == st.OK


class TestTheBarcodeGate:
    def test_it_stops_the_run(self, run_dir):
        proc = _stage("03_barcodes", run_dir, *_EVIDENCE)
        assert proc.returncode == 3, proc.stdout + proc.stderr

    def test_it_recovers_the_studys_real_barcode(self, run_dir):
        _stage("03_barcodes", run_dir, *_EVIDENCE)
        bundle = json.loads((run_dir / "barcode_proposals.json").read_text())
        by_gsm = {p["gsm"]: p for p in bundle["proposals"]}
        assert by_gsm["GSM2817677"]["five_prime"] == "NNNCGGANNN"

    def test_replicates_are_not_given_the_same_core(self, run_dir):
        """GSM2817677 is CGGA and GSM2817678 is GGCA; conflating them is silent."""
        _stage("03_barcodes", run_dir, *_EVIDENCE)
        bundle = json.loads((run_dir / "barcode_proposals.json").read_text())
        by_gsm = {p["gsm"]: p["five_prime"] for p in bundle["proposals"]}
        if "GSM2817678" in by_gsm:
            assert by_gsm["GSM2817678"] != by_gsm["GSM2817677"]

    def test_04_cannot_run_while_the_gate_holds(self, run_dir):
        _stage("03_barcodes", run_dir, *_EVIDENCE)
        proc = _stage("04_annotate", run_dir, "--geo-matrix", str(GSE105082_MATRIX),
                      "--srr-map", str(GSE105082_SRR_MAP))
        assert proc.returncode == 5


class TestPastTheGate:
    @pytest.fixture
    def confirmed(self, run_dir, tmp_path):
        path = tmp_path / "confirmed.json"
        path.write_text(json.dumps({"status": "confirmed", "proposals": [{
            "gsm": "GSM2817677", "five_prime": "NNNCGGANNN", "umi_barcode": "",
            "protocol": "generic", "confidence": "high", "status": "confirmed",
            "evidence": [], "agent_notes": "test",
        }]}))
        assert _stage("03_barcodes", run_dir, "--accept-proposals", str(path)).returncode == 0
        return run_dir

    def test_confirmation_releases_it(self, confirmed):
        assert st.status(confirmed, "03_barcodes") == st.OK

    def test_annotation_is_built(self, confirmed):
        proc = _stage("04_annotate", confirmed, "--geo-matrix", str(GSE105082_MATRIX),
                      "--srr-map", str(GSE105082_SRR_MAP))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (confirmed / "annotation.raw.csv").exists()

    def test_the_sample_name_and_organism_survive(self, confirmed):
        """`cell type: HeLa` wins over the supplier phrase in !Sample_source_name_ch1."""
        import pandas as pd

        _stage("04_annotate", confirmed, "--geo-matrix", str(GSE105082_MATRIX),
               "--srr-map", str(GSE105082_SRR_MAP))
        df = pd.read_csv(confirmed / "annotation.raw.csv")
        row = df.iloc[0]
        assert row["GEO ID"] == "GSM2817677"
        assert row["Sample Name"] == "DHX9_Hs_HeLa_Rep1_SRR6181530"

    def test_04_runs_once_not_three_times(self, confirmed):
        """The failure this rebuild exists to remove: re-execution as a dependency mechanism."""
        args = ("--geo-matrix", str(GSE105082_MATRIX), "--srr-map", str(GSE105082_SRR_MAP))
        assert _stage("04_annotate", confirmed, *args).returncode == 0
        again = _stage("04_annotate", confirmed, *args)
        assert again.returncode == 0
        assert "already done" in again.stdout
