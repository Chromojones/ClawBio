"""A stage flag does what it says, or it does not exist.

Where an action is outward-facing and left to the agent, the stage prints the exact command
to run instead of reporting an action it never took.
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

PARAMS = {"move_umi_to_header": "false", "umi_separator": "rbc:",
          "skip_umi_dedupe": "false", "paired": "first"}


def _stage(name, out, *extra):
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / f"{name}.py"), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=120,
    )


def _flags(name):
    spec = importlib.util.spec_from_file_location(f"s_{name}", SKILL_DIR / "stages" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {s for a in module.build_parser()._actions for s in a.option_strings}


class TestNoFlagClaimsAnActionItNeverTakes:
    def test_12_has_no_submit(self):
        assert "--submit" not in _flags("12_analysis")

    def test_210_has_no_submit(self):
        assert "--submit" not in _flags("210_upload")

    def test_11_has_no_repair(self):
        assert "--repair" not in _flags("11_verify")

    def test_110_has_no_poll_interval(self):
        assert "--poll-interval" not in _flags("110_import")

    def test_110_keeps_submit_because_it_does_submit(self):
        assert "--submit" in _flags("110_import")

    def test_01_has_no_sizes(self):
        """The size ceiling runs in 109, where the rows exist."""
        assert "--sizes" not in _flags("01_study")


@pytest.fixture
def approved(tmp_path):
    """A run with parameters released at 108, ready for 12."""
    out = tmp_path / "run"
    out.mkdir()
    st.record(out, "108_params", st.OK)
    st.set_route(out, line="direct", protocol="iCLIP", reason="test")
    st.set_study(out, params_confirmed=True, project_id="123", sample_count=2)
    (out / "pipeline_params.json").write_text(json.dumps(PARAMS, indent=2) + "\n")
    return out


class Test12PrintsTheRunner:
    def test_it_prints_the_command_to_run(self, approved):
        proc = _stage("12_analysis", approved, "--no-reference-reason", "test")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert f"bash {approved / 'run_analysis.sh'}" in proc.stdout
        assert "submitted" not in proc.stdout

    def test_the_name_filter_reaches_the_runner(self, approved):
        _stage("12_analysis", approved, "--no-reference-reason", "test",
               "--sample-name-filter", "SRR61815(30|34)")
        assert "--filter sample_name 'SRR61815(30|34)'" in (approved / "run_analysis.sh").read_text()

    def test_an_empty_filter_warns_and_is_left_out_of_the_runner(self, approved):
        """An empty regex selects every sample of that method in the project."""
        proc = _stage("12_analysis", approved, "--no-reference-reason", "test")
        assert "--sample-name-filter" in proc.stdout
        assert "sample_name" not in (approved / "run_analysis.sh").read_text()

    def test_the_runner_sources_no_credentials_file(self, approved):
        """Nothing writes .flow_credentials.env."""
        _stage("12_analysis", approved, "--no-reference-reason", "test")
        assert ".flow_credentials.env" not in (approved / "run_analysis.sh").read_text()


class Test01SaysWhatItDidNotCheck:
    def test_availability_not_checked_is_stated(self, tmp_path):
        out = tmp_path / "run"
        out.mkdir()
        st.record(out, "00_setup", st.OK)
        st.set_study(out, accession="GSE1")
        proc = _stage("01_study", out)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "availability: not checked" in proc.stdout
        assert "search: not run" in proc.stdout


ON_FLOW = {"projects": [], "samples": [],
           "data": [{"id": "1", "filename": "SRX1453676_SRR1.fastq.gz"}]}
NEIGHBOUR = {"projects": [{"id": "808005400407594329", "name": "Global-iCLIP_05_26"}],
             "samples": [], "data": []}
NOTHING = {"projects": [], "samples": [], "data": []}


class Test01ReadsTheSearch:
    """`--search-results` is read by the stage: an accession match stops the run."""

    def _run(self, tmp_path, results):
        out = tmp_path / "run"
        out.mkdir()
        st.record(out, "00_setup", st.OK)
        st.set_study(out, accession="GSE75418")
        search = tmp_path / "search.json"
        search.write_text(json.dumps(results))
        return out, _stage("01_study", out, "--search-results", str(search))

    def test_no_match_proceeds(self, tmp_path):
        out, proc = self._run(tmp_path, {"SRX1453676": NOTHING, "SAFB1": NOTHING})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert json.loads((out / "study_check.json").read_text())["already_uploaded"] is False

    def test_an_accession_match_stops_the_run(self, tmp_path):
        _, proc = self._run(tmp_path, {"SRX1453676": ON_FLOW})
        assert proc.returncode == 4, proc.stdout + proc.stderr
        assert "ALREADY PRESENT" in proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr

    def test_a_target_match_is_shown_not_blocking(self, tmp_path):
        _, proc = self._run(tmp_path, {"SRX1453676": NOTHING, "SAFB1": NEIGHBOUR})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "808005400407594329" in proc.stdout

    def test_a_failed_accession_query_stops_the_run(self, tmp_path):
        _, proc = self._run(tmp_path, {"SRX1453676": None, "SAFB1": NOTHING})
        assert proc.returncode == 4, proc.stdout + proc.stderr
        assert "INCONCLUSIVE" in proc.stdout + proc.stderr


@pytest.fixture
def local_ready(tmp_path):
    """A local-line run with parameters released, reads recorded at 201."""
    out = tmp_path / "run"
    out.mkdir()
    st.record(out, "108_params", st.OK)
    st.record(out, "201_fetch", st.OK)
    st.set_route(out, line="local", protocol="iCLIP", reason="test")
    st.set_study(out, params_confirmed=True, project_id="123")
    (out / "pipeline_params.json").write_text(json.dumps(PARAMS) + "\n")
    (out / "fetch_plan.json").write_text(json.dumps({"fastq_dir": "/data/fq"}) + "\n")
    (out / "annotation.raw.csv").write_text(
        "File,Sample Name,Type\n"
        "SRR1.fastq.gz,DHX9_Hs_HeLa_Rep1_SRR1,CLIP\n"
        "SRR2.fastq.gz,DHX9_Hs_HeLa_Rep2_SRR2,CLIP\n")
    return out


class Test210PrintsTheUpload:
    def test_it_prints_the_vendored_upload_command(self, local_ready):
        proc = _stage("210_upload", local_ready)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        text = proc.stdout
        assert "uploadsample_flowbio_v6.py" in text
        assert f"--input {local_ready / 'upload_sheet.csv'}" in text
        assert "--rows 1-2" in text
        assert "--project-id 123" in text
        assert "--base-dir /data/fq" in text
        assert "--dry-run" in text

    def test_a_missing_fastq_dir_is_named_not_guessed(self, local_ready):
        (local_ready / "fetch_plan.json").write_text(json.dumps({"fastq_dir": ""}) + "\n")
        proc = _stage("210_upload", local_ready)
        assert "--base-dir <fastq_dir>" in proc.stdout
        assert "--fastq-dir" in proc.stdout


class Test201RecordsAnAbsoluteReadsDirectory:
    """210 prints `--base-dir` from what 201 recorded; a relative path breaks from another cwd."""

    def test_a_relative_fastq_dir_is_recorded_absolute(self, tmp_path):
        out = tmp_path / "run"
        out.mkdir()
        st.record(out, "06_route", st.OK)
        st.set_route(out, line="local", protocol="iCLIP", reason="test")
        proc = _stage("201_fetch", out, "--fastq-dir", "demo")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        recorded = json.loads((out / "fetch_plan.json").read_text())["fastq_dir"]
        assert Path(recorded).is_absolute(), recorded
        assert Path(recorded) == (SKILL_DIR / "demo").resolve()


class Test210NormalisesTheAnnotation:
    def test_the_upload_sheet_carries_the_canonical_no_uv(self, local_ready):
        (local_ready / "annotation.raw.csv").write_text(
            "File,Sample Name,Type,Purification Target Annotation\n"
            "SRR1.fastq.gz,TARDBP_Hs_HeLa_noUV_Rep1_SRR1,CLIP,nouv\n")
        proc = _stage("210_upload", local_ready)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert ",noUV" in (local_ready / "upload_sheet.csv").read_text()
