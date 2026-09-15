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

    def test_a_literal_barcode_in_characteristics_ch1_is_a_hint(self, tmp_path):
        """A barcode stated in `characteristics_ch1` (`barcode: NNNGGTTNN`, GSE149561) is a
        hint.
        """
        matrix = tmp_path / "series_matrix.txt"
        matrix.write_text(
            "!Series_geo_accession\t\"GSE149561\"\n"
            '!Sample_geo_accession\t"GSM4504851"\t"GSM4504852"\n'
            '!Sample_title\t"SYNCRIP - rep1"\t"IgG - rep1"\n'
            '!Sample_characteristics_ch1\t"barcode: NNNGGTTNN"\t"barcode: NNNTTGTNN"\n'
        )
        data = parse_geo_matrix(matrix)
        assert data["samples"]["GSM4504851"]["barcode_hints"] == ["NNNGGTTNN"]
        assert data["samples"]["GSM4504852"]["barcode_hints"] == ["NNNTTGTNN"]
