"""A gate blocks, and only a human artefact releases it.

A gate exits 3, not 4: awaiting approval is not a failure. A gated stage does not satisfy a
prerequisite, or the gate is decorative.

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

#: Positions 1-3 randomer, 4-7 fixed barcode, 8-9 randomer: the Koenig NNNXXXXNN layout.
COMPOSITIONS = {
    "S1": [4.1, 3.8, 4.4, 74.9, 75.2, 74.1, 75.8, 4.0, 3.9, 14.2, 16.0, 13.1],
}

#: The real shape `write_proposal_bundle` emits and `load_confirmed_proposals` reads. A
#: proposal is only confirmed when a person sets status=confirmed on it.
def _bundle(status):
    return {"status": "pending_confirmation", "proposals": [{
        "gsm": "GSM1", "five_prime": "NNNGGCGNN", "umi_barcode": "",
        "protocol": "generic", "confidence": "high", "status": status,
        "evidence": [], "agent_notes": "test",
    }]}


def _stage(name, out, *extra):
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / name), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
    )


def _compositions(out):
    """A composition file, so 03 has something to work from in a bare run dir."""
    import json
    path = out / "compositions.json"
    path.write_text(json.dumps(COMPOSITIONS))
    return str(path)


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
        assert (out / "barcode_proposals.json").exists()

    def test_composition_is_reported_as_a_range(self, tmp_path):
        """Composition cannot settle the last base; GSE131210 position 13 read 7.9% off even."""
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        comps = tmp_path / "comps.json"; comps.write_text(json.dumps(COMPOSITIONS))
        proc = _stage("03_barcodes.py", out, "--compositions", str(comps))
        assert proc.returncode == 3
        described = json.loads((out / "barcode_composition.json").read_text())["S1"]
        assert "UMI" in described

    def test_confirming_releases_the_gate(self, tmp_path):
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        confirmed = tmp_path / "confirmed.json"
        confirmed.write_text(json.dumps(_bundle("confirmed")))
        proc = _stage("03_barcodes.py", out, "--accept-proposals", str(confirmed))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert json.loads((out / "barcodes.json").read_text())["GSM1"]["five_prime"]

    def test_an_unconfirmed_bundle_does_not_release_the_gate(self, tmp_path):
        """Handing back the file unchanged is not approval."""
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        pending = tmp_path / "pending.json"
        pending.write_text(json.dumps(_bundle("pending_confirmation")))
        assert _stage("03_barcodes.py", out, "--accept-proposals", str(pending)).returncode == 3

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


class TestGateFourReachesTheSubmission:
    """The analysis runner is on the stages' path, and it re-asks nothing 108 settled."""

    def test_a_stage_generates_the_analysis_script(self):
        from pathlib import Path

        stages = Path(__file__).resolve().parent.parent.parent / "stages"
        callers = [p.name for p in stages.glob("*.py") if "write_analysis_script" in p.read_text()]
        assert callers == ["12_analysis.py"], callers

    def test_the_generated_script_does_not_re_gate(self, tmp_path):
        """Submission is not a fourth gate, and the runner must not smuggle one back in."""
        from lib.flow_stages import write_analysis_script

        path = write_analysis_script(
            tmp_path, analysis_script=tmp_path / "a.py", project_id="P1",
            pipeline_params={"paired": "second"}, sample_name_filter="",
            experimental_method="eCLIP",
        )
        text = path.read_text()
        assert "analysis_params.confirmed.json" not in text
        assert "exit 3" not in text


class TestTheGatePointsAtTheReviewFile:
    """The barcode gate names `CONFIRM_BARCODES.md`, the file a person reviews, not only the JSON.
    """

    def test_it_names_the_markdown_review_file(self, tmp_path):
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        proc = _stage("03_barcodes.py", out, "--compositions", _compositions(out))
        assert proc.returncode == 3
        assert "CONFIRM_BARCODES.md" in proc.stdout, proc.stdout

    def test_it_still_names_the_file_to_edit_and_pass_back(self, tmp_path):
        out = tmp_path / "run"; out.mkdir()
        _through_02(out)
        proc = _stage("03_barcodes.py", out, "--compositions", _compositions(out))
        assert "barcode_proposals.json" in proc.stdout
        assert "--accept-proposals" in proc.stdout
