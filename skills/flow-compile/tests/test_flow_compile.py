"""Tests for flow-compile orchestrator."""

import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from flow_compile import (
    DEMO_MATRIX,
    DEMO_PUBMED_CACHE,
    DEMO_SRR_MAP,
    GSE105082_MATRIX,
    GSE105082_SRR_MAP,
    EXIT_PAUSED,
    run_pipeline,
)
from lib.barcode_resolver import resolve_barcodes
from lib.geo_matrix import parse_geo_matrix
from lib.organism import normalize_organism


class TestGeoMatrix:
    def test_parse_demo_matrix(self):
        data = parse_geo_matrix(DEMO_MATRIX)
        assert data["series"]["geo_accession"] == "GSE118265"
        assert len(data["samples"]) == 2


class TestBarcodeResolution:
    def test_flash_barcodes(self):
        data = parse_geo_matrix(DEMO_MATRIX)
        resolutions = resolve_barcodes(data["samples"], protocol="flash")
        by_gsm = {r.gsm: r for r in resolutions}
        assert by_gsm["GSM3323898"].five_prime == "NNNNNGTGGAANN"
        assert by_gsm["GSM3323900"].five_prime == "NNNNNTGGAACNN"


class TestOrganismInPipeline:
    def test_demo_organism_codes_only(self, tmp_path):
        out = tmp_path / "demo"
        result, _paused = run_pipeline(out, DEMO_MATRIX, DEMO_SRR_MAP, pubmed_cache=DEMO_PUBMED_CACHE)
        import pandas as pd

        df = pd.read_csv(out / "annotation.csv")
        assert set(df["Organism"].unique()) <= {"Hs"}
        assert normalize_organism("Homo sapiens") == "Hs"


class TestDemoPipeline:
    def test_demo_runs_without_error(self, tmp_path):
        out = tmp_path / "demo"
        result, paused = run_pipeline(out, DEMO_MATRIX, DEMO_SRR_MAP, pubmed_cache=DEMO_PUBMED_CACHE)
        assert paused is False
        assert result is not None
        assert result.barcodes_resolved == 2
        assert "pubmed-summariser" in result.chain
        assert (out / "annotation.csv").exists()
        assert (out / "annotation.xlsx").exists()
        assert (out / "report.md").exists()

    def test_report_contains_disclaimer(self, tmp_path):
        out = tmp_path / "demo"
        run_pipeline(out, DEMO_MATRIX, DEMO_SRR_MAP, pubmed_cache=DEMO_PUBMED_CACHE)
        assert "Not a medical device" in (out / "report.md").read_text()

    def test_report_documents_chain(self, tmp_path):
        out = tmp_path / "demo"
        run_pipeline(out, DEMO_MATRIX, DEMO_SRR_MAP, pubmed_cache=DEMO_PUBMED_CACHE)
        report = (out / "report.md").read_text()
        assert "pubmed-summariser" in report
        assert "fastq-headers" in report or "Pipeline params" in report

    def test_flagged_papers_from_cache(self, tmp_path):
        out = tmp_path / "demo"
        run_pipeline(out, DEMO_MATRIX, DEMO_SRR_MAP, pubmed_cache=DEMO_PUBMED_CACHE)
        flagged = json.loads((out / "flagged_papers.json").read_text())
        assert flagged[0]["pmid"] == "31802123"

    def test_prefetch_script(self, tmp_path):
        out = tmp_path / "demo"
        run_pipeline(out, DEMO_MATRIX, DEMO_SRR_MAP, pubmed_cache=DEMO_PUBMED_CACHE, write_prefetch=True, max_files=2)
        script = (out / "prefetch.sh").read_text()
        assert "prefetch SRR7657599" in script


class TestGSE105082Case:
    def test_pauses_for_barcode_confirmation(self, tmp_path):
        out = tmp_path / "gse105082"
        result, paused = run_pipeline(
            out,
            GSE105082_MATRIX,
            GSE105082_SRR_MAP,
            paper_texts=[(f"paper:PMC", SKILL_DIR / "demo" / "paper_PMC6307142_iclip_excerpt.txt")],
            geo_cache_dir=SKILL_DIR / "demo",
        )
        assert paused is True
        assert result is None
        proposals = json.loads((out / "barcode_proposals.json").read_text())
        assert proposals["status"] == "pending_confirmation"
        assert any(p["five_prime"] == "NNNCGGANNN" for p in proposals["proposals"])
        by_gsm = {p["gsm"]: p for p in proposals["proposals"]}
        assert by_gsm["GSM2817678"]["five_prime"] == "NNNGGCANNN"

    def test_headers_and_params_with_fastq(self, tmp_path):
        fq_dir = tmp_path / "fastq"
        fq_dir.mkdir()
        demo = SKILL_DIR / "demo" / "SRR6181530.fastq.gz"
        if not demo.exists():
            pytest.skip("demo FASTQ missing")
        import shutil

        shutil.copy(demo, fq_dir / "SRR6181530.fastq.gz")
        shutil.copy(demo, fq_dir / "SRR6181534.fastq.gz")

        out = tmp_path / "out"
        proposals_path = tmp_path / "proposals.json"
        proposals_path.write_text(
            json.dumps(
                {
                    "status": "confirmed",
                    "proposals": [
                        {
                            "gsm": "GSM2817677",
                            "five_prime": "NNNCGGANNN",
                            "umi_barcode": "",
                            "protocol": "generic",
                            "confidence": "high",
                            "status": "confirmed",
                            "evidence": [],
                            "agent_notes": "test",
                        },
                        {
                            "gsm": "GSM2817678",
                            "five_prime": "NNNGGCANNN",
                            "umi_barcode": "",
                            "protocol": "generic",
                            "confidence": "high",
                            "status": "confirmed",
                            "evidence": [],
                            "agent_notes": "test",
                        },
                    ],
                }
            )
        )
        result, paused = run_pipeline(
            out,
            GSE105082_MATRIX,
            GSE105082_SRR_MAP,
            accept_proposals=proposals_path,
            fastq_dir=fq_dir,
            flow_project_id="997999200849251656",
        )
        assert paused is False
        params = json.loads((out / "pipeline_params.json").read_text())
        assert params["move_umi_to_header"] == "true"
        assert params["umi_separator"] == "_"
        assert params["umi_header_format"] == "NNNNNNNNNN"
        assert (out / "headers.txt").exists()
        assert (out / "clean_fastq.sh").exists()
        assert result.flow_project_id == "997999200849251656"
        import pandas as pd

        df = pd.read_csv(out / "annotation.csv")
        names = dict(zip(df["GEO ID"], df["Sample Name"]))
        assert names["GSM2817677"] == "DHX9_Hs_ATCC_Cell_Lines_Rep1_SRR6181530"
        assert names["GSM2817678"] == "DHX9_Hs_ATCC_Cell_Lines_Rep2_SRR6181534"
