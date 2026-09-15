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


def _routed(out, *, header_state="raw", protocol="iCLIP", barcodes=None, read_structure=""):
    """Stand up what 108 depends on: a decided route, a header state, confirmed barcodes."""
    st.record(out, "06_route", st.OK)
    st.set_route(out, line="direct", protocol=protocol, reason="test")
    st.set_study(out, header_state=header_state, read_structure=read_structure)
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


class TestProcessedReads:
    """Reads trimmed of their block before submission (SRR5646571) get no extraction and no
    deduplication, whatever barcode the metadata records."""

    def test_processed_raw_reads_skip_extraction_and_dedup(self, tmp_path):
        _routed(tmp_path, read_structure="processed",
                barcodes={"GSM1": {"five_prime": "NNNATCGNN"}})
        proc = _stage(tmp_path)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        params = json.loads((tmp_path / "pipeline_params.json").read_text())
        assert params["move_umi_to_header"] == "false"
        assert params["skip_umi_dedupe"] == "true"
        assert "umi_header_format" not in params
        assert "processed" in proc.stdout.lower()

    def test_a_umi_still_in_the_header_is_deduplicated(self, tmp_path):
        """Processed reads with `rbc:` in the name still carry their UMI."""
        _routed(tmp_path, header_state="rbc_end", read_structure="processed",
                barcodes={"GSM1": {"five_prime": "NNNATCGNN"}})
        proc = _stage(tmp_path)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        params = json.loads((tmp_path / "pipeline_params.json").read_text())
        assert params["umi_separator"] == "rbc:"
        assert params.get("skip_umi_dedupe", "false") == "false"

    def test_untrimmed_reads_extract_as_before(self, tmp_path):
        _routed(tmp_path, read_structure="untrimmed",
                barcodes={"GSM1": {"five_prime": "N" * 11}})
        proc = _stage(tmp_path)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        params = json.loads((tmp_path / "pipeline_params.json").read_text())
        assert params["umi_header_format"] == "N" * 11
