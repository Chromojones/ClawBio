"""A gate must block, and must be releasable only by a human artefact.

The barcode and analysis-parameter hooks are hard stops: the run pauses, the evidence is
written out, and the only way past is supplying a confirmed file. Two properties matter, and
neither is obvious from reading the stage.

**A gate is not a failure.** Exit 3, not 4. The old orchestrator printed a warning and carried
on for both "this barcode is awaiting approval" and "this barcode contradicts the reads", which
is how an unapproved barcode could reach an upload.

**A gated stage does not satisfy a prerequisite.** `state.require()` must refuse to let a later
stage run against a stage that stopped at a gate, or the gate is decorative.

Story: FAILURES.md#approval-hooks
"""

import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402

PY = sys.executable
COMPOSITIONS = {
    # Positions 1-3 randomer, 4-7 fixed barcode, 8-9 randomer: the Koenig NNNXXXXNN layout.
    "S1": [4.1, 3.8, 4.4, 74.9, 75.2, 74.1, 75.8, 4.0, 3.9, 14.2, 16.0, 13.1],
}


def _stage(name, out, *extra):
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / name), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
    )


def _through_02(out):
    """Stand up the prerequisites 03 declares, without running the real stages."""
    st.record(out, "00_setup", st.OK)
    st.record(out, "02_index", st.OK)


class TestTheBarcodeGate:
    def test_proposals_gate_rather_than_pass(self, tmp_path):
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        comps = tmp_path / "comps.json"
        comps.write_text(json.dumps(COMPOSITIONS))
        proc = _stage("03_barcodes.py", out, "--compositions", str(comps))
        assert proc.returncode == 3, proc.stdout + proc.stderr

    def test_the_gate_names_what_releases_it(self, tmp_path):
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        comps = tmp_path / "comps.json"; comps.write_text(json.dumps(COMPOSITIONS))
        proc = _stage("03_barcodes.py", out, "--compositions", str(comps))
        assert "--accept-proposals" in proc.stdout

    def test_the_evidence_is_written_for_review(self, tmp_path):
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        comps = tmp_path / "comps.json"; comps.write_text(json.dumps(COMPOSITIONS))
        _stage("03_barcodes.py", out, "--compositions", str(comps))
        proposals = json.loads((out / "barcode_proposals.json").read_text())
        assert "S1" in proposals and proposals["S1"]["evidence"]

    def test_the_umi_length_is_offered_as_a_range(self, tmp_path):
        """Composition cannot settle the last base; GSE131210 position 13 read 7.9% off even."""
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        comps = tmp_path / "comps.json"; comps.write_text(json.dumps(COMPOSITIONS))
        _stage("03_barcodes.py", out, "--compositions", str(comps))
        proposals = json.loads((out / "barcode_proposals.json").read_text())
        entry = proposals["S1"]
        assert "umi_len_min" in entry and "umi_len_max" in entry
        assert "umi_len" not in entry, "a single UMI length would be an invented number"

    def test_confirming_releases_the_gate(self, tmp_path):
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        confirmed = tmp_path / "confirmed.json"
        confirmed.write_text(json.dumps({"S1": {"barcode": "NNNGGCGNN"}}))
        proc = _stage("03_barcodes.py", out, "--accept-proposals", str(confirmed))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (out / "barcodes.json").exists()

    def test_no_evidence_at_all_still_gates(self, tmp_path):
        """Absent evidence must not read as "nothing to approve"."""
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        assert _stage("03_barcodes.py", out).returncode == 3


class TestAGatedStageBlocksTheNextOne:
    def test_require_refuses_a_gated_prerequisite(self, tmp_path):
        """Otherwise the gate is decorative: the next stage runs anyway."""
        out = tmp_path / "run"; out.mkdir()
        st.record(out, "03_barcodes", st.GATED, release="--accept-proposals")
        try:
            st.require(out, "03_barcodes")
        except st.PrerequisiteError as exc:
            assert "--accept-proposals" in str(exc)
            return
        raise AssertionError("a gated stage satisfied a prerequisite")

    def test_gate_and_check_failure_are_different_exit_codes(self, tmp_path):
        """Awaiting approval (3) is not the same as contradicted by the data (4)."""
        from stages._common import CHECK_FAILED, GATE

        assert GATE != CHECK_FAILED
