"""Stage 11 checks the imported samples against the sheet that produced them.

Rows are compared in Flow's own keys: `import_sheet.csv` on the direct line, the upload sheet
mapped through `sra_import.COLUMN_MAP` on the local line. Differences become a
`flow_edit_samples.py` edits file that the agent applies, not an edit the stage claims to make.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402

PY = sys.executable

SHEET = [
    {"accession": "SRX1", "sample_type": "CLIP", "project": "123",
     "name": "DHX9_Hs_HeLa_Rep1_SRR1", "purification_target": "DHX9",
     "purification_target__annotation": "nFLAG"},
    {"accession": "SRX2", "sample_type": "CLIP", "project": "123",
     "name": "DHX9_Hs_HeLa_Rep2_SRR2", "purification_target": "DHX9",
     "purification_target__annotation": "nFLAG"},
]


def live(name, *, annotation="nFLAG"):
    """A sample body in the shape `GET /samples/{id}` returns."""
    return {
        "id": f"id-{name}", "name": name, "project": {"id": "123"},
        "metadata": {"purification_target": {"value": "DHX9", "annotation": annotation}},
        "filesets": [{"data": [{"id": "d1"}]}],
    }


def _stage(out, live_samples):
    path = out / "live.json"
    path.write_text(json.dumps(live_samples) + "\n")
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / "11_verify.py"), "--output", str(out),
         "--live-samples", str(path)],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=120,
    )


def _write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def imported(tmp_path):
    """Direct line: 110 submitted a job, the sheet it sent is on disk."""
    out = tmp_path / "run"
    out.mkdir()
    st.record(out, "06_route", st.OK)
    st.record(out, "110_import", st.OK)
    st.set_route(out, line="direct", protocol="iCLIP", reason="test")
    st.set_study(out, project_id="123", import_job="J1")
    _write_csv(out / "import_sheet.csv", SHEET)
    return out


class TestTheDirectLine:
    def test_a_matching_import_passes(self, imported):
        proc = _stage(imported, [live(r["name"]) for r in SHEET])
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_a_dropped_annotation_becomes_an_edits_file(self, imported):
        proc = _stage(imported, [live(SHEET[0]["name"], annotation=""), live(SHEET[1]["name"])])
        assert proc.returncode == 4, proc.stdout + proc.stderr
        rows = list(csv.DictReader((imported / "repair_edits.csv").open()))
        assert rows == [{"sample_id": f"id-{SHEET[0]['name']}",
                         "purification_target__annotation": "nFLAG"}]
        said = proc.stdout + proc.stderr
        assert "flow_edit_samples.py" in said and "--edits" in said and "--dry-run" in said

    def test_a_missing_sample_is_a_failed_import_not_a_repair(self, imported):
        proc = _stage(imported, [live(SHEET[0]["name"])])
        assert proc.returncode == 4, proc.stdout + proc.stderr
        assert SHEET[1]["name"] in proc.stdout + proc.stderr
        assert "not imported" in proc.stdout + proc.stderr
        assert not (imported / "repair_edits.csv").exists()

    def test_a_dry_run_import_is_not_an_import(self, imported):
        """110 without --submit records ok; nothing reached Flow, so there is nothing to verify."""
        st.set_study(imported, import_job="")
        proc = _stage(imported, [live(r["name"]) for r in SHEET])
        assert proc.returncode == 4, proc.stdout + proc.stderr
        assert "--submit" in proc.stdout + proc.stderr

    def test_it_waits_for_the_import_stage(self, tmp_path):
        out = tmp_path / "early"
        out.mkdir()
        st.record(out, "06_route", st.OK)
        st.set_route(out, line="direct", protocol="iCLIP", reason="test")
        _write_csv(out / "import_sheet.csv", SHEET)
        assert _stage(out, [live(r["name"]) for r in SHEET]).returncode == 5


class TestTheLocalLine:
    def test_the_upload_sheet_is_compared_in_flow_keys(self, tmp_path):
        out = tmp_path / "local"
        out.mkdir()
        st.record(out, "06_route", st.OK)
        st.record(out, "210_upload", st.OK)
        st.set_route(out, line="local", protocol="iCLIP", reason="test")
        st.set_study(out, project_id="123")
        _write_csv(out / "upload_sheet.csv", [
            {"File": "SRR1.fastq.gz", "Sample Name": SHEET[0]["name"],
             "Protein (Purification Target)": "DHX9", "Purification Target Annotation": "nFLAG"},
        ])
        proc = _stage(out, [live(SHEET[0]["name"])])
        assert proc.returncode == 0, proc.stdout + proc.stderr
