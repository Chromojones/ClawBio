"""`flow_compile.py` as a driver: it knows the order, the stages know the work.

The old entry point was 1,026 lines holding every stage body in one function whose control
flow WAS the dependency graph. What survives is the part that could not move into a stage:
which stage comes next, and which line this run is on. `catalog.json` and `clawbio.py` invoke
this path, so it keeps working as a command.

`--status` and `--next` exist because the stage model has a real failure mode: sixteen scripts
is easy to lose your place in. The driver answers "where am I" from `state.json` rather than
from the user's memory.

Story: FAILURES.md#driver
"""

import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402

DRIVER = SKILL_DIR / "flow_compile.py"


def _run(*argv):
    return subprocess.run([sys.executable, str(DRIVER), *argv],
                          capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90)


class TestTheOrderIsDeclaredOnce:
    def test_the_trunk_is_in_order(self):
        from flow_compile import TRUNK

        assert [s.split("_")[0] for s in TRUNK] == ["00", "01", "02", "03", "04", "05", "06"]

    def test_each_line_starts_where_the_route_points(self):
        from flow_compile import DIRECT_LINE, LOCAL_LINE

        assert DIRECT_LINE[0].startswith("101")
        assert LOCAL_LINE[0].startswith("201")

    def test_the_shared_params_stage_is_on_both_lines(self):
        """108 is the third hard stop and neither line may skip it."""
        from flow_compile import DIRECT_LINE, LOCAL_LINE

        assert any(s.startswith("108") for s in DIRECT_LINE)
        assert any(s.startswith("108") for s in LOCAL_LINE)

    def test_every_named_stage_exists_on_disk(self):
        """A typo in the order table would otherwise surface only at run time."""
        from flow_compile import DELIVERY, DIRECT_LINE, LOCAL_LINE, TRUNK

        for name in [*TRUNK, *DIRECT_LINE, *LOCAL_LINE, *DELIVERY]:
            assert (SKILL_DIR / "stages" / f"{name}.py").exists(), name


class TestStatus:
    def test_status_on_a_fresh_dir_says_nothing_has_run(self, tmp_path):
        proc = _run("--status", "--output", str(tmp_path))
        assert proc.returncode == 0
        assert "00_setup" in proc.stdout

    def test_status_reports_a_completed_stage(self, tmp_path):
        st.record(tmp_path, "00_setup", st.OK)
        proc = _run("--status", "--output", str(tmp_path))
        assert "00_setup" in proc.stdout and "ok" in proc.stdout

    def test_status_shows_a_gate_as_waiting_not_failed(self, tmp_path):
        """A gate is not a failure, and the status must not read like one."""
        st.record(tmp_path, "03_barcodes", st.GATED, release="--accept-proposals")
        proc = _run("--status", "--output", str(tmp_path))
        assert "--accept-proposals" in proc.stdout


class TestNext:
    def test_next_on_a_fresh_dir_is_the_first_stage(self, tmp_path):
        proc = _run("--next", "--output", str(tmp_path))
        assert "00_setup" in proc.stdout

    def test_next_advances(self, tmp_path):
        st.record(tmp_path, "00_setup", st.OK)
        proc = _run("--next", "--output", str(tmp_path))
        assert "01_study" in proc.stdout

    def test_next_repeats_a_gated_stage_rather_than_skipping_it(self, tmp_path):
        """Everything before the gate must be complete, or `next` rightly points there instead."""
        for name in ("00_setup", "01_study", "02_index"):
            st.record(tmp_path, name, st.OK)
        st.record(tmp_path, "03_barcodes", st.GATED, release="--accept-proposals")
        proc = _run("--next", "--output", str(tmp_path))
        assert "03_barcodes" in proc.stdout

    def test_next_follows_the_route_once_it_is_decided(self, tmp_path):
        for name in ("00_setup", "01_study", "02_index", "03_barcodes",
                     "04_annotate", "05_metadata", "06_route"):
            st.record(tmp_path, name, st.OK)
        st.set_route(tmp_path, line="local", protocol="iCLIP", reason="not in SRA")
        proc = _run("--next", "--output", str(tmp_path))
        assert "201_fetch" in proc.stdout

    def test_the_direct_route_leads_to_101(self, tmp_path):
        for name in ("00_setup", "01_study", "02_index", "03_barcodes",
                     "04_annotate", "05_metadata", "06_route"):
            st.record(tmp_path, name, st.OK)
        st.set_route(tmp_path, line="direct", protocol="eCLIP", reason="in SRA")
        proc = _run("--next", "--output", str(tmp_path))
        assert "101_preview" in proc.stdout


class TestItStaysADriver:
    def test_it_is_small(self):
        """The point of the split. If this grows back, the stages are not carrying their work."""
        n = len(DRIVER.read_text().splitlines())
        assert n <= 260, f"flow_compile.py is {n} lines"

    def test_it_does_not_import_pandas(self):
        """A driver decides order; anything touching a dataframe belongs in a stage."""
        assert "import pandas" not in DRIVER.read_text()
