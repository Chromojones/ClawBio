"""An `--offline` run makes no network call at 04_annotate.

A PMID in the matrix would otherwise send 04 to Europe PMC, and an offline run stalls on the
timeout.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402
from tests.conftest import GSE105082_MATRIX, GSE105082_SRR_MAP  # noqa: E402


def _stage_module():
    spec = importlib.util.spec_from_file_location(
        "stage_04", SKILL_DIR / "stages" / "04_annotate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def confirmed(tmp_path):
    """A run past the barcode gate, declared offline at setup."""
    out = tmp_path / "run"
    out.mkdir()
    st.record(out, "03_barcodes", st.OK)
    st.set_study(out, accession="GSE105082", offline=True)
    (out / "barcodes.json").write_text(json.dumps(
        {"GSM2817677": {"five_prime": "NNNCGGANNN", "umi_barcode": "",
                        "protocol": "iCLIP", "notes": "test"}}) + "\n")
    return out


def test_an_offline_run_makes_no_network_call(confirmed, monkeypatch):
    """The demo matrix carries `!Series_pubmed_id 30591072`, so this is the live path."""
    import lib.paper_metadata_enrich as pme

    def boom(*a, **k):
        raise AssertionError("offline run attempted a network fetch")

    monkeypatch.setattr(pme, "_http_get", boom)
    code = _stage_module().main([
        "--output", str(confirmed),
        "--geo-matrix", str(GSE105082_MATRIX),
        "--srr-map", str(GSE105082_SRR_MAP),
    ])
    assert code == 0
    assert (confirmed / "annotation.raw.csv").exists()
