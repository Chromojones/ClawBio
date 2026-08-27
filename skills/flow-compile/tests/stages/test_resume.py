"""Running a completed stage again must do nothing, for every stage there is.

The old orchestrator required running the same command three times — compile, download,
re-compile, clean, re-compile — because one command owned both `annotation.csv` and the FASTQ
filenames, and the filenames only settled once the reads were on disk. Re-execution WAS the
dependency mechanism, so "run it again" was load-bearing rather than harmless.

Under the stage model it must be harmless. This is checked generically over `stages/`, the same
way the contract is, because the property has to hold for stages nobody has written yet.

Story: FAILURES.md#state-contract
"""

import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402
from stages._common import prerequisites_of  # noqa: E402


def _load(stage):
    """Import a stage module by path; the names start with digits, so `import` cannot."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"stage_{stage.stem}", stage)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared_inputs(stage, out):
    """The inputs the stage itself declares, so the recorded digest can match a real run."""
    module = _load(stage)
    fn = getattr(module, "_inputs", None)
    if fn is None:
        return []
    args = module.build_parser().parse_args(["--output", str(out)])
    return list(fn(args, out))


def _satisfy_prerequisites(out, stage):
    """Mark this stage's declared prerequisites complete.

    A re-run happens in a directory where the earlier stages already ran, so a test that omits
    them is testing the prerequisite check, not re-entrancy. The two are checked separately:
    prerequisites in test_stage_contract.py, re-entrancy here.
    """
    for name in prerequisites_of(stage):
        st.record(out, name, st.OK)

STAGES = sorted(p for p in (SKILL_DIR / "stages").glob("*.py") if not p.name.startswith("_"))
IDS = [p.stem for p in STAGES]


@pytest.mark.skipif(not STAGES, reason="no stages yet")
class TestReentrancy:
    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_a_completed_stage_short_circuits(self, stage, tmp_path):
        """Marked done with matching inputs, the stage reports done and does not re-run.

        Stages with required arguments of their own are skipped here rather than fed invented
        values: a real re-run supplies the same arguments as the first run, and argparse
        rightly rejects a re-run that drops half of them. The guarantee itself is tested
        directly against `run_stage` in TestTheGuaranteeItself below, so nothing goes
        unchecked; this loop confirms the stages that CAN be invoked bare do short-circuit.
        """
        out = tmp_path / "run"
        out.mkdir()
        name = stage.stem
        _satisfy_prerequisites(out, stage)
        try:
            inputs = _declared_inputs(stage, out)
        except SystemExit:
            pytest.skip(f"{name} takes required arguments; see TestTheGuaranteeItself")
        st.record(out, name, st.OK, outputs=[], inputs=inputs, args=["--output", str(out)])
        proc = subprocess.run(
            [sys.executable, str(stage), "--output", str(out)],
            capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
        )
        if proc.returncode == 2 and "required" in proc.stderr:
            pytest.skip(f"{name} takes required arguments; see TestTheGuaranteeItself")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "already done" in proc.stdout

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_force_overrides_the_short_circuit(self, stage, tmp_path):
        """--force must actually reach the body, which without prerequisites means exit != 0."""
        out = tmp_path / "run"
        out.mkdir()
        name = stage.stem
        _satisfy_prerequisites(out, stage)
        try:
            inputs = _declared_inputs(stage, out)
        except SystemExit:
            pytest.skip(f"{name} takes required arguments; see TestTheGuaranteeItself")
        st.record(out, name, st.OK, outputs=[], inputs=inputs, args=["--output", str(out)])
        proc = subprocess.run(
            [sys.executable, str(stage), "--output", str(out), "--force"],
            capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
        )
        assert "already done" not in proc.stdout


class TestTheGuaranteeItself:
    """`run_stage` re-entrancy, tested where it is implemented rather than per stage."""

    def _stage(self, tmp_path, calls, extra_argv=()):
        from stages._common import parser_for, run_stage

        def body(args, out):
            calls.append(1)
            (out / "made.txt").write_text("x")
            return {}

        return lambda: run_stage(
            "synthetic", body, parser=parser_for("synthetic", "test"),
            outputs=["made.txt"], argv=["--output", str(tmp_path), *extra_argv],
        )

    def test_the_body_runs_once_across_two_invocations(self, tmp_path):
        calls = []
        run = self._stage(tmp_path, calls)
        assert run() == 0
        assert run() == 0
        assert len(calls) == 1, "the body ran twice"

    def test_force_runs_it_again(self, tmp_path):
        calls = []
        assert self._stage(tmp_path, calls)() == 0
        assert self._stage(tmp_path, calls, ["--force"])() == 0
        assert len(calls) == 2

    def test_a_deleted_output_runs_it_again(self, tmp_path):
        calls = []
        run = self._stage(tmp_path, calls)
        assert run() == 0
        (tmp_path / "made.txt").unlink()
        assert run() == 0
        assert len(calls) == 2


@pytest.mark.skipif(not STAGES, reason="no stages yet")
class TestTheDigestIsWhatDecides:
    def test_a_changed_input_re_runs(self, tmp_path):
        out = tmp_path / "run"
        out.mkdir()
        src = out / "in.csv"
        src.write_text("a\n")
        st.record(out, "x", st.OK, outputs=[], inputs=[src])
        assert st.begin(out, "x", inputs=[src]) is False
        src.write_text("b\n")
        assert st.begin(out, "x", inputs=[src]) is True

    def test_a_deleted_output_re_runs(self, tmp_path):
        """Completed with its artefacts gone is not completed, for the next stage's purposes."""
        out = tmp_path / "run"
        out.mkdir()
        made = out / "made.txt"
        made.write_text("x")
        st.record(out, "x", st.OK, outputs=["made.txt"], inputs=[])
        assert st.begin(out, "x", inputs=[]) is False
        made.unlink()
        assert st.begin(out, "x", inputs=[]) is True
