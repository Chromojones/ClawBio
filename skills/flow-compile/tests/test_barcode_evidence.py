"""Tests for agent-assisted barcode evidence extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.barcode_evidence import extract_evidence_from_text, merge_proposal_from_evidence
from lib.barcode_extract import extract_barcodes_for_gsms, write_proposal_bundle

SKILL_DIR = Path(__file__).resolve().parent.parent
GEO_SNIPPET = SKILL_DIR / "demo" / "geo_GSM9118554.txt"


class TestGSM9118554Extraction:
    def test_geo_barcode_trim_15bp(self):
        text = GEO_SNIPPET.read_text()
        evidence = extract_evidence_from_text(text, "geo:GSM9118554")
        kinds = {e.kind for e in evidence}
        assert "geo_barcode_trim_bp" in kinds
        assert "min_read_barcode_umi" in kinds
        proposal = merge_proposal_from_evidence("GSM9118554", evidence)
        assert proposal.five_prime.startswith("N")
        assert len(proposal.five_prime) >= 15
        assert proposal.status == "pending_confirmation"

    def test_hnrnph_case_pauses(self, tmp_path):
        proposals = extract_barcodes_for_gsms(
            ["GSM9118554", "GSM9118555"],
            paper_texts=[("paper:PMC6307142", SKILL_DIR / "demo" / "paper_PMC6307142_iclip_excerpt.txt")],
            geo_cache_dir=SKILL_DIR / "demo",
        )
        path = write_proposal_bundle(tmp_path, proposals)
        assert path.exists()
        assert (tmp_path / "CONFIRM_BARCODES.md").exists()
        assert all(p.status == "pending_confirmation" for p in proposals)
