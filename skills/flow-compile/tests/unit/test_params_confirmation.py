"""The fourth gate must not come back through the generated script.

`12_analysis` is a check, not a gate: once `108_params` is released with `--accept-params` the
parameters *are* the decision, and asking again at submission is how a gate stops meaning
anything. The stage honours that — but the runner it wrote did not. `run_analysis.sh` exited 3
unless the operator hand-copied `pipeline_params.json` to `analysis_params.confirmed.json`,
and pointed at a `CONFIRM_ANALYSIS_PARAMS.md` that `write_analysis_params_hook` would have
written if anything had called it. So the script demanded a file nothing told anyone to make,
to re-answer a question already settled two stages earlier.

The comparison machinery went with it. `compare_confirmed_params` existed only to diff the
derived params against a copy of themselves.

Story: FAILURES.md#params-confirmation
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))


class TestTheGeneratedRunnerDoesNotReGate:
    @pytest.fixture
    def script(self, tmp_path):
        from lib.flow_stages import write_analysis_script

        path = write_analysis_script(
            tmp_path,
            analysis_script=tmp_path / "flowrunanalysis_flowbio.py",
            project_id="P1",
            pipeline_params={"paired": "second"},
            sample_name_filter="",
            experimental_method="eCLIP",
        )
        return path.read_text()

    def test_it_demands_no_confirmation_file(self, script):
        assert "analysis_params.confirmed.json" not in script
        assert "CONFIRM_ANALYSIS_PARAMS" not in script

    def test_it_does_not_exit_3(self, script):
        """Exit 3 is the gate code. This script gates nothing; 108 already did."""
        assert "exit 3" not in script

    def test_it_still_submits_with_the_approved_params(self, script):
        assert "pipeline_params.json" in script
        assert "--params-json" in script

    def test_the_params_file_is_still_written(self, tmp_path):
        from lib.flow_stages import write_analysis_script

        write_analysis_script(
            tmp_path, analysis_script=tmp_path / "a.py", project_id="P1",
            pipeline_params={"paired": "second"}, sample_name_filter="",
            experimental_method="eCLIP",
        )
        assert (tmp_path / "pipeline_params.json").exists()


class TestTheMachineryIsGone:
    def test_compare_confirmed_params_is_retired(self):
        import lib.pipeline_params as pp

        assert not hasattr(pp, "compare_confirmed_params")

    def test_the_dead_hook_is_retired(self):
        """`write_analysis_params_hook` wrote the review file nothing ever asked for."""
        import lib.pipeline_params as pp

        assert not hasattr(pp, "write_analysis_params_hook")
