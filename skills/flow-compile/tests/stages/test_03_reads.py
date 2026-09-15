"""03 can read the deposited reads: an in-line block becomes a proposal, and processed reads
are marked so the barcode is recorded as metadata only.

Story: FAILURES.md#read-structure
"""

import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402


def _stage_module():
    spec = importlib.util.spec_from_file_location("stage_03", SKILL_DIR / "stages" / "03_barcodes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _records(seqs, prefix):
    out = []
    for i, s in enumerate(seqs, 1):
        out += [f"@{prefix}.{i} {i}/1", s, "+", "F" * len(s)]
    return out


def _untrimmed(n=300, seed=1):
    rng = random.Random(seed)
    reads = []
    for _ in range(n):
        head = "".join(rng.choices("ACGT", weights=[2, 2, 2, 4], k=8)) \
            + "".join(rng.choice("AT") for _ in range(2)) + "T"
        # genomic-like: 12-20% off even, never uniform
        insert = "".join(rng.choices("ACGT", weights=[3, 1, 1, 3], k=rng.randint(10, 30)))
        reads.append((head + insert + "AGATCGGAAGAGCACACGTCTGAACTCCAGTCACATCACG")[:50])
    return reads


def _processed(n=300, seed=2):
    rng = random.Random(seed)
    return ["".join(rng.choices("ACGT", k=rng.randint(15, 59))) for _ in range(n)]


@pytest.fixture
def indexed(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    st.record(out, "00_setup", st.OK)
    st.record(out, "02_index", st.OK)
    (out / "sheet_rows.json").write_text(json.dumps([
        {"accession": "SRX1", "srr": "SRR1", "gsm": "GSM1", "sample_type": "CLIP"},
        {"accession": "SRX2", "srr": "SRR2", "gsm": "GSM2", "sample_type": "CLIP"},
    ]) + "\n")
    return out


def _stub(monkeypatch, records_by_run, load_format="FASTQ"):
    import lib.sra_header_preview as shp

    def fake_preview_runs(runs, **kwargs):
        return ({r: records_by_run[r] for r in runs if r in records_by_run},
                {r: "ena" for r in runs})

    monkeypatch.setattr(shp, "preview_runs", fake_preview_runs)
    monkeypatch.setattr(shp, "sra_load_format", lambda run: load_format)


def _proposals(out):
    return {p["gsm"]: p for p in json.loads((out / "barcode_proposals.json").read_text())["proposals"]}


class TestAnInlineBlockBecomesAProposal:
    def test_the_block_is_proposed_as_all_n_with_its_range(self, indexed, monkeypatch):
        """GSE228970: 8 variable bases and an A/T spacer, 11–12 nt; the length needs confirming."""
        _stub(monkeypatch, {"SRR1": _records(_untrimmed(), "SRR1"),
                            "SRR2": _records(_untrimmed(seed=3), "SRR2")})
        code = _stage_module().main(["--output", str(indexed), "--fetch-reads"])
        assert code == 3
        p = _proposals(indexed)["GSM1"]
        assert p["five_prime"] == "N" * 11
        assert p["confidence"] == "low"
        assert any(e["kind"] == "composition" and "11" in e["notes"] for e in p["evidence"])
        assert (indexed / "read_structure.json").exists()

    def test_a_documented_barcode_outranks_the_block(self, indexed, monkeypatch, tmp_path):
        paper = tmp_path / "methods.txt"
        paper.write_text("Libraries carried the 5' barcodes (NNNGGCANNN and NNNCGGANNN).\n")
        _stub(monkeypatch, {"SRR1": _records(_untrimmed(), "SRR1")})
        _stage_module().main(["--output", str(indexed), "--fetch-reads", "--paper-text", str(paper)])
        assert _proposals(indexed)["GSM1"]["five_prime"] == "NNNGGCANNN"


class TestProcessedReadsAreMarked:
    def test_no_block_is_proposed_and_the_notes_say_why(self, indexed, monkeypatch, capsys):
        _stub(monkeypatch, {"SRR1": _records(_processed(), "SRR1"),
                            "SRR2": _records(_processed(seed=4), "SRR2")}, load_format="BAM")
        code = _stage_module().main(["--output", str(indexed), "--fetch-reads"])
        assert code == 3
        p = _proposals(indexed)["GSM1"]
        assert p["five_prime"] == ""
        assert "processed" in p["agent_notes"].lower()
        assert "metadata" in p["agent_notes"].lower()
        assert "processed" in capsys.readouterr().out.lower()
        assert "processed" in (indexed / "CONFIRM_BARCODES.md").read_text().lower()
