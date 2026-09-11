"""GEO series-matrix parsing.

GSM2817677 carries `CGGA` and GSM2817678 `GGCA`, differing only by that core; a resolver that
ignored it would demultiplex each replicate into the other.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.geo_matrix import (  # noqa: E402
    parse_geo_matrix,
    scan_barcode_patterns,
    scan_replicate_barcode_cores,
)
from tests.conftest import GSE105082_MATRIX  # noqa: E402


class TestParsing:
    def test_the_series_is_read(self):
        data = parse_geo_matrix(GSE105082_MATRIX)
        assert data["series"]["geo_accession"] == "GSE105082"

    def test_all_24_samples_are_found(self):
        data = parse_geo_matrix(GSE105082_MATRIX)
        assert "GSM2817677" in data["samples"]
        assert len(data["samples"]) == 24


class TestBarcodeScanning:
    def test_patterns_are_found_in_prose(self):
        assert "NNNCGGANNN" in scan_barcode_patterns("Barcodes (NNNCGGANNN and NNNGGCANNN)")

    def test_prose_without_a_pattern_yields_nothing(self):
        assert scan_barcode_patterns("Homo sapiens HeLa") == []

    def test_a_core_is_recovered_from_a_supplementary_filename(self):
        url = "GSM2817678_rsem_GGCA.trimmed.nodup.no10.fastq.transcript.sort.nodup.bw"
        assert scan_replicate_barcode_cores(url) == ["GGCA"]

    def test_a_filename_without_a_core_yields_nothing(self):
        assert scan_replicate_barcode_cores("no core here") == []

    def test_replicates_get_different_cores(self):
        """Conflating these two would demultiplex each replicate into the other, silently."""
        data = parse_geo_matrix(GSE105082_MATRIX)
        assert data["samples"]["GSM2817677"]["replicate_barcode_cores"] == ["CGGA"]
        assert data["samples"]["GSM2817678"]["replicate_barcode_cores"] == ["GGCA"]
