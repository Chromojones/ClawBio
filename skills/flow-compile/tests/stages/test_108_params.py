"""Stage 108 derives the UMI parameters from the barcode confirmed at 03.

A raw-header study gets its `umi_header_format` (all-N of the barcode's length) from
`barcodes.json`; without it `check_umi_params` refuses and no flag can supply one.

Story: FAILURES.md#read-structure
"""

import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402

PY = sys.executable


def _stage(out, *extra):
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / "108_params.py"), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90,
    )


def _routed(out, *, header_state="raw", protocol="iCLIP", barcodes=None):
    """Stand up what 108 depends on: a decided route, a header state, confirmed barcodes."""
    st.record(out, "06_route", st.OK)
    st.set_route(out, line="direct", protocol=protocol, reason="test")
    st.set_study(out, header_state=header_state)
    (out / "barcodes.json").write_text(json.dumps(barcodes or {}, indent=2) + "\n")


class TestTheBarcodeFeedsTheParams:
    def test_a_raw_header_derives_the_format_from_the_confirmed_barcode(self, tmp_path):
        """Raw state + a 10-nt barcode must GATE (exit 3), not die on a missing format."""
        _routed(tmp_path, barcodes={"GSM1": {"five_prime": "NNNCGGANNN"}})
        proc = _stage(tmp_path)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        params = json.loads((tmp_path / "pipeline_params.json").read_text())
        assert params["umi_header_format"] == "N" * 10

    def test_mixed_barcode_lengths_are_refused(self, tmp_path):
        """One run takes one umi_header_format; two lengths cannot both be right."""
        _routed(tmp_path, barcodes={"GSM1": {"five_prime": "NNNCGGANNN"},
                                    "GSM2": {"five_prime": "NNNGGCGNN"}})
        proc = _stage(tmp_path)
        assert proc.returncode == 4, proc.stdout + proc.stderr
        assert "length" in (proc.stdout + proc.stderr).lower()

    def test_a_prepended_randomer_needs_no_format(self, tmp_path):
        """randomer_prefix: nothing is extracted, so no format is derived or required."""
        _routed(tmp_path, header_state="randomer_prefix",
                barcodes={"GSM1": {"five_prime": "NNNCGGANNN"}})
        proc = _stage(tmp_path)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        params = json.loads((tmp_path / "pipeline_params.json").read_text())
        assert "umi_header_format" not in params

    def test_accept_params_releases_the_gate(self, tmp_path):
        _routed(tmp_path, barcodes={"GSM1": {"five_prime": "NNNCGGANNN"}})
        proc = _stage(tmp_path, "--accept-params")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert st.study(tmp_path).get("params_confirmed") is True
