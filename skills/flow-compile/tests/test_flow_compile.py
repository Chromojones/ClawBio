"""Tests for flow-compile orchestrator (GSE105082 / GSM2817677 demo)."""

import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from flow_compile import GSE105082_MATRIX, GSE105082_SRR_MAP, run_pipeline
from lib.geo_matrix import parse_geo_matrix, scan_barcode_patterns, scan_replicate_barcode_cores
from lib.organism import normalize_organism


class TestGeoMatrix:
    def test_parse_gse105082_full_matrix(self):
        data = parse_geo_matrix(GSE105082_MATRIX)
        assert data["series"]["geo_accession"] == "GSE105082"
        assert "GSM2817677" in data["samples"]
        assert len(data["samples"]) == 24

    def test_scan_barcode_patterns(self):
        assert "NNNCGGANNN" in scan_barcode_patterns("Barcodes (NNNCGGANNN and NNNGGCANNN)")
        assert scan_barcode_patterns("Homo sapiens HeLa") == []

    def test_scan_replicate_barcode_cores(self):
        url = "GSM2817678_rsem_GGCA.trimmed.nodup.no10.fastq.transcript.sort.nodup.bw"
        assert scan_replicate_barcode_cores(url) == ["GGCA"]
        assert scan_replicate_barcode_cores("no core here") == []

    def test_matrix_replicate_cores_gse105082(self):
        data = parse_geo_matrix(GSE105082_MATRIX)
        assert data["samples"]["GSM2817677"]["replicate_barcode_cores"] == ["CGGA"]
        assert data["samples"]["GSM2817678"]["replicate_barcode_cores"] == ["GGCA"]


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
        assert proposals["proposals"][0]["gsm"] == "GSM2817677"
        assert proposals["proposals"][0]["five_prime"] == "NNNCGGANNN"
        assert (out / "CONFIRM_BARCODES.md").exists()

    def test_headers_and_params_with_fastq(self, tmp_path):
        fq_dir = tmp_path / "fastq"
        fq_dir.mkdir()
        demo = SKILL_DIR / "demo" / "SRR6181530.fastq.gz"
        if not demo.exists():
            pytest.skip("demo FASTQ missing")
        import shutil

        shutil.copy(demo, fq_dir / "SRR6181530.fastq.gz")

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
                    ],
                }
            )
        )
        result, paused = run_pipeline(
            out,
            GSE105082_MATRIX,
            GSE105082_SRR_MAP,
            accept_proposals=proposals_path,
            # GSE105082 has no antibody in GEO and no --paper-text here, so the metadata
            # gate legitimately blocks on an empty Purification Agent. Approving it is
            # what the researcher does after reviewing CONFIRM_METADATA.md.
            accept_metadata=True,
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
        assert len(df) == 1
        assert df.iloc[0]["GEO ID"] == "GSM2817677"
        # `cell type: HeLa` now wins over the supplier phrase in !Sample_source_name_ch1
        # ("ATCC Cell Lines") — see lib/flow_annotate.resolve_source.
        assert df.iloc[0]["Sample Name"] == "DHX9_Hs_HeLa_Rep1_SRR6181530"
        assert normalize_organism(df.iloc[0]["Organism"]) == "Hs"
