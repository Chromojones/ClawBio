"""The 18-per-execution ceiling must hold without anyone remembering a flag.

Stage 12 read ``study.get("sample_count")``, a key no stage wrote, so the ceiling that
replaced the fourth hard stop was only checked when the operator happened to pass
``--samples`` — and a rule enforced only when remembered is not a rule. 04_annotate is the
sole writer of annotation content, so the count of its rows is the count of samples, and it
records it; 12 then enforces the ceiling by default.

Story: FAILURES.md#execution-batching
"""

import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402

PY = sys.executable

PARAMS = {"move_umi_to_header": "false", "umi_separator": "rbc:",
          "skip_umi_dedupe": "false", "paired": "first"}


def _stage(out, *extra):
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / "12_analysis.py"), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
    )


def _confirmed(out, *, sample_count=0):
    st.record(out, "108_params", st.OK)
    st.set_route(out, line="direct", protocol="iCLIP", reason="test")
    st.set_study(out, params_confirmed=True, project_id="123")
    if sample_count:
        st.set_study(out, sample_count=sample_count)
    (out / "pipeline_params.json").write_text(json.dumps(PARAMS, indent=2) + "\n")


class TestTheCeilingHoldsByDefault:
    def test_the_recorded_count_is_used_without_a_flag(self, tmp_path):
        _confirmed(tmp_path, sample_count=40)
        proc = _stage(tmp_path, "--no-reference-reason", "test")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "40 sample(s)" in proc.stdout
        assert "sample count unknown" not in proc.stdout

    def test_a_split_over_the_ceiling_is_refused(self, tmp_path):
        """40 samples in one execution is 40 per execution; the ceiling is 18."""
        _confirmed(tmp_path, sample_count=40)
        proc = _stage(tmp_path, "--no-reference-reason", "test", "--chunks", "1")
        assert proc.returncode == 4, proc.stdout + proc.stderr

    def test_an_explicit_count_still_wins(self, tmp_path):
        """--samples stays as the override for a partial re-run."""
        _confirmed(tmp_path, sample_count=40)
        proc = _stage(tmp_path, "--no-reference-reason", "test", "--samples", "6")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "6 sample(s)" in proc.stdout
