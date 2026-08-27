"""One contract, checked generically over every stage that exists.

Seventeen scripts is more surface than one command, and the plan accepted that trade on one
condition: the guarantee lives entirely in `stages/_common.py` and is enforced by a loop over
whatever is in `stages/`, never by per-stage assertions. A per-stage test suite would pass
while a new stage quietly skipped `require()`, wrote outside the output directory, or invented
its own exit codes — which is exactly how the current orchestrator accumulated three ways of
reporting the same failure.

So this file deliberately discovers stages rather than listing them. Adding a stage that breaks
the contract fails here without anyone remembering to add a test.

Exit codes, uniform:

    0  ok
    2  usage error
    3  gate — a human artefact is required before continuing
    4  check failed — the data is wrong
    5  prerequisite stage not ok

Story: FAILURES.md#stage-contract
"""

import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

STAGES_DIR = SKILL_DIR / "stages"


def _stages():
    if not STAGES_DIR.is_dir():
        return []
    return sorted(p for p in STAGES_DIR.glob("*.py") if not p.name.startswith("_"))


STAGES = _stages()
IDS = [p.stem for p in STAGES]


@pytest.mark.skipif(not STAGES, reason="no stages yet")
class TestEveryStage:
    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_is_executable_and_says_how(self, stage):
        """A stage is chmod +x, so it needs the line that makes that mean something."""
        import os

        assert stage.read_text().startswith("#!"), f"{stage.name} has no shebang"
        assert os.access(stage, os.X_OK), f"{stage.name} is not executable"

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_is_numbered(self, stage):
        """The number is the running order; a stage without one has no place in the flow."""
        assert stage.stem[:2].isdigit(), f"{stage.name} does not start with a two-digit number"

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_declares_the_common_contract(self, stage):
        """Every stage routes through `_common`; none rolls its own argument or exit handling."""
        assert "from stages._common import" in stage.read_text() or \
               "from _common import" in stage.read_text(), f"{stage.name} bypasses stages/_common.py"

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_requires_an_output_dir(self, stage):
        """Everything a stage writes is addressed relative to `--output`.

        Checked through `--help` rather than the source, because a stage getting `--output`
        from `parser_for` is the contract working, not a stage evading it.
        """
        proc = subprocess.run(
            [sys.executable, str(stage), "--help"],
            capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
        )
        assert "--output" in proc.stdout, f"{stage.name} does not take --output"

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_help_works_without_side_effects(self, stage):
        proc = subprocess.run(
            [sys.executable, str(stage), "--help"],
            capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
        )
        assert proc.returncode == 0, proc.stderr[-800:]
        assert stage.stem in proc.stdout or "usage" in proc.stdout.lower()

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_missing_output_is_a_usage_error_not_a_traceback(self, stage):
        proc = subprocess.run(
            [sys.executable, str(stage)],
            capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
        )
        assert proc.returncode == 2, f"expected usage exit 2, got {proc.returncode}"
        assert "Traceback" not in proc.stderr

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_stays_under_the_size_limit(self, stage):
        """A stage past 150 lines is doing more than one thing and should be split."""
        n = len(stage.read_text().splitlines())
        assert n <= 150, f"{stage.name} is {n} lines"

    @pytest.mark.parametrize("stage", STAGES, ids=IDS)
    def test_refuses_to_run_before_its_prerequisites(self, stage, tmp_path):
        """A stage with prerequisites exits 5 on an empty output dir, and names what is missing.

        The first stage has none and is skipped; anything else that runs happily against a bare
        directory is reading state it never checked for.
        """
        from stages._common import prerequisites_of

        needs = prerequisites_of(stage)
        if not needs:
            pytest.skip(f"{stage.stem} has no prerequisites")
        out = tmp_path / "run"
        out.mkdir()
        proc = subprocess.run(
            [sys.executable, str(stage), "--output", str(out)],
            capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
        )
        assert proc.returncode == 5, f"expected prerequisite exit 5, got {proc.returncode}"
        assert any(n in proc.stdout + proc.stderr for n in needs)


@pytest.mark.skipif(not STAGES, reason="no stages yet")
class TestTheSetOfStages:
    def test_numbers_are_unique_within_a_line(self):
        """Two stages sharing a number is ambiguous in the flow and in the metro map."""
        numbers = [p.stem.split("_")[0] for p in STAGES]
        assert len(numbers) == len(set(numbers)), f"duplicate stage numbers: {numbers}"

    def test_the_trunk_starts_at_00(self):
        assert IDS[0].startswith("00"), f"first stage is {IDS[0]}"
