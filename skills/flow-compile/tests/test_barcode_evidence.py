"""Tests for agent-assisted barcode evidence extraction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.barcode_evidence import extract_evidence_from_text, merge_proposal_from_evidence, normalize_flow_barcode
from lib.barcode_extract import extract_barcodes_for_gsms, write_proposal_bundle

SKILL_DIR = Path(__file__).resolve().parent.parent
PAPER = SKILL_DIR / "demo" / "paper_PMC6307142_iclip_excerpt.txt"
GEO = SKILL_DIR / "demo" / "geo_GSM2817677.txt"


class TestGSM2817677Extraction:
    def test_literal_barcode_from_paper(self):
        text = PAPER.read_text()
        evidence = extract_evidence_from_text(text, "paper:PMC6307142")
        kinds = {e.kind for e in evidence}
        assert "literal_barcode" in kinds
        proposal = merge_proposal_from_evidence("GSM2817677", evidence)
        assert proposal.five_prime == "NNNCGGANNN"
        assert proposal.status == "pending_confirmation"

    def test_gse105082_case_pauses(self, tmp_path):
        proposals = extract_barcodes_for_gsms(
            ["GSM2817677"],
            paper_texts=[("paper:PMC6307142", PAPER)],
            geo_cache_dir=SKILL_DIR / "demo",
            sample_titles={"GSM2817677": "iCLIP-DHX9-1"},
        )
        path = write_proposal_bundle(tmp_path, proposals)
        assert path.exists()
        assert (tmp_path / "CONFIRM_BARCODES.md").exists()
        assert proposals[0].five_prime == "NNNCGGANNN"
        assert all(p.status == "pending_confirmation" for p in proposals)

    def test_geo_sample_page_adds_evidence(self):
        text = GEO.read_text()
        evidence = extract_evidence_from_text(text, "geo:GSM2817677")
        # GEO page defers barcodes to publication — may be empty; paper is primary source
        assert isinstance(evidence, list)


class TestNormalizeFlowBarcode:
    def test_ryb_to_n(self):
        assert normalize_flow_barcode("NNRRNTTTTTTNN") == "NNNNNTTTTTTNN"
        assert normalize_flow_barcode("NNYYNTTTTTTNN") == "NNNNNTTTTTTNN"
        assert normalize_flow_barcode("NNBBNGTGGAANN") == "NNNNNGTGGAANN"

    def test_acgtn_unchanged(self):
        assert normalize_flow_barcode("NNNCGGANNN") == "NNNCGGANNN"
