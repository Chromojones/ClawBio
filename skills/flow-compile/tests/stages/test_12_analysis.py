"""The 18-per-execution ceiling holds without a flag.

04_annotate records the sample count and 12 enforces the ceiling from it; `--samples` overrides
for a partial re-run.

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


class TestNoReferenceReasonWithoutAReferenceFile:
    """GSE149561: the first Rattus norvegicus CLIP study on the account, so there is no
    completed same-organism run to pass as `--reference-params` at all — only a reason.
    `body()` built `reference = {}` when `--reference-params` was omitted, not `None`, so
    `cross_check_reference` took the "a reference WAS supplied but shares no keys" branch
    instead of the "no reference_params, but a reason was declared" branch — the reason was
    silently ignored and the message read as "NOT COMPARED" (more alarming, and not what
    happened) regardless of what `--no-reference-reason` said.
    """

    def test_the_declared_reason_reaches_the_cross_check(self, tmp_path):
        _confirmed(tmp_path, sample_count=6)
        proc = _stage(tmp_path, "--no-reference-reason", "first rat CLIP study; nothing to compare")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "NOT COMPARED" not in proc.stdout
        assert "first rat CLIP study; nothing to compare" in proc.stdout
