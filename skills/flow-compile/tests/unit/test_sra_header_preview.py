"""The remote FASTQ header preview that gates `flowbio samples import`.

ENA renders `@<run>.<n> <original spot name>`, the form Flow fetches, so ENA is the primary path.
`fastq-dump --origfmt`, the fallback, drops the comment field the UMI check reads, so the verdict
depends on the fetch source.

Story: FAILURES.md#defline-provenance
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.sra_header_preview import (  # noqa: E402
    inspection_from_header_records,
    parse_ena_fastq_urls,
)

# Real shape of the ENA filereport response: a run_accession column precedes fastq_ftp,
# and paired runs put both mates in one semicolon-joined field.
ENA_TSV_PAIRED = (
    "run_accession\tfastq_ftp\n"
    "SRR21863801\tftp.sra.ebi.ac.uk/vol1/fastq/SRR218/001/SRR21863801/SRR21863801_1.fastq.gz;"
    "ftp.sra.ebi.ac.uk/vol1/fastq/SRR218/001/SRR21863801/SRR21863801_2.fastq.gz\n"
)
ENA_TSV_SINGLE = (
    "run_accession\tfastq_ftp\n"
    "ERR039788\tftp.sra.ebi.ac.uk/vol1/fastq/ERR039/ERR039788/ERR039788.fastq.gz\n"
)


class TestParseEnaFilereport:
    def test_paired_run_yields_both_mates_as_https(self):
        urls = parse_ena_fastq_urls(ENA_TSV_PAIRED)
        assert len(urls) == 2
        assert urls[0].startswith("https://ftp.sra.ebi.ac.uk/")
        assert urls[0].endswith("_1.fastq.gz")
        assert urls[1].endswith("_2.fastq.gz")

    def test_single_end_run_yields_one_url(self):
        assert len(parse_ena_fastq_urls(ENA_TSV_SINGLE)) == 1

    def test_column_order_is_not_assumed(self):
        """The FASTQ URL is found by content, not by field index."""
        swapped = (
            "fastq_ftp\trun_accession\n"
            "ftp.sra.ebi.ac.uk/vol1/fastq/ERR039/ERR039788/ERR039788.fastq.gz\tERR039788\n"
        )
        urls = parse_ena_fastq_urls(swapped)
        assert urls == ["https://ftp.sra.ebi.ac.uk/vol1/fastq/ERR039/ERR039788/ERR039788.fastq.gz"]

    @pytest.mark.parametrize("payload", ["", "run_accession\tfastq_ftp\n", "not a tsv"])
    def test_empty_or_unusable_payload_yields_nothing(self, payload):
        assert parse_ena_fastq_urls(payload) == []


# 4-line FASTQ records exactly as sampled from the pools.
ECLIP_RECORDS = [
    "@SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1",
    "NAGCAATGGCGCGTGGAGGGGGGGGCGGCCCGCCGGCGGGGACAGGGGGACCGGC",
    "+",
    "#AAFFJJJ",
]
RBC_RECORDS = [
    "@D00611:270:CBQTGANXX:5:1101:1445:2149:rbc:CACTTG 1:N:0:ATCACG",
    "AGCTTAGCTAGCTACCTATATCTTGGTCTTGGCCG",
    "+",
    "BBBFFFFF",
]


class TestInspectionFromRecords:
    def test_no_rbc_means_umi_still_in_read_sequence(self):
        inspection = inspection_from_header_records({"SRR21863801": ECLIP_RECORDS})
        assert inspection.has_rbc is False
        assert "barcode likely in read sequence" in inspection.notes

    def test_rbc_tag_is_detected_from_a_remote_snippet(self):
        inspection = inspection_from_header_records({"SRRX": RBC_RECORDS})
        assert inspection.has_rbc is True

    def test_sample_headers_are_retained_for_headers_txt(self):
        inspection = inspection_from_header_records({"SRR21863801": ECLIP_RECORDS})
        assert any(line.startswith("@SRR21863801") for line in inspection.sample_headers)

    def test_empty_preview_is_safe(self):
        inspection = inspection_from_header_records({})
        assert inspection.has_rbc is False
        assert inspection.sample_headers == []


class TestUmiInHeaderBlocksSraDirect:
    """A UMI in the header cannot survive SRA-direct import.

    ENA's defline pushes the original header, with its `rbc:` UMI, into the comment; aligners drop
    the comment and UMICollapse fails with `No match found` (GSE297587).
    """

    ENA_UMI_IN_COMMENT = [
        "@SRR33628723.1 NS500784:933:H5W2CBGXN:1:11101:8390:10741:N:0:1rbc:TAGGATAAA/1",
        "NAGCAATGGCGCG", "+", "#AAFFJJJ",
    ]
    CLEAN_UMI_IN_NAME = [
        "@SRR33628723.1_NS500784:933:H5W2CBGXN:1:11101:8390:10741:N:0:1rbc:TAGGATAAA_1",
        "NAGCAATGGCGCG", "+", "#AAFFJJJ",
    ]
    NO_UMI = [
        "@SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1",
        "NAGCAATGGCGCG", "+", "#AAFFJJJ",
    ]

    def test_umi_stranded_in_comment_is_flagged(self):
        insp = inspection_from_header_records({"SRR33628723": self.ENA_UMI_IN_COMMENT})
        assert insp.has_rbc is True
        assert insp.umi_in_comment is True
        assert "comment" in insp.notes.lower()

    def test_umi_already_in_read_name_is_not_flagged(self):
        insp = inspection_from_header_records({"SRR33628723": self.CLEAN_UMI_IN_NAME})
        assert insp.has_rbc is True
        assert insp.umi_in_comment is False

    def test_header_without_a_umi_is_not_flagged(self):
        insp = inspection_from_header_records({"SRR21863801": self.NO_UMI})
        assert insp.has_rbc is False
        assert insp.umi_in_comment is False


class TestTheFallbackCannotClearTheCommentVerdict:
    """`fastq-dump --origfmt` has no comment field, so it cannot clear the verdict.

    Measured on SRR33628723 (sra-tools 3.2.1)::

        ENA fastq_ftp         @SRR33628723.1 NS500784:…:1rbc:TAGGATAAA/1   UMI in the comment
        fastq-dump (default)  @SRR33628723.1 NS500784:…:1rbc:TAGGATAAA length=83
        fastq-dump --origfmt  @NS500784:…:1rbc:TAGGATAAA                  no comment field

    ENA and Flow render `@<run>.<n> <spot name>`, so what `--origfmt` shows as the name becomes the
    comment.

    Story: FAILURES.md#defline-provenance
    """

    ORIGFMT_WITH_UMI = "@NS500784:933:H5W2CBGXN:1:11101:8390:10741:N:0:1rbc:TAGGATAAA"
    ORIGFMT_NO_UMI = "@K00180:212:H7VCTBBXX:5:1101:20598:1033"
    ENA_WITH_UMI = "@SRR33628723.1 NS500784:933:H5W2CBGXN:1:11101:8390:10741:N:0:1rbc:TAGGATAAA/1"

    def test_origfmt_output_is_not_mistaken_for_safe(self):
        from lib.sra_header_preview import umi_is_stranded_in_comment

        assert umi_is_stranded_in_comment(self.ORIGFMT_WITH_UMI, source="fastq-dump") is True

    def test_a_fallback_header_without_a_umi_is_not_over_blocked(self):
        from lib.sra_header_preview import umi_is_stranded_in_comment

        assert umi_is_stranded_in_comment(self.ORIGFMT_NO_UMI, source="fastq-dump") is False

    def test_the_ena_verdict_is_unchanged(self):
        from lib.sra_header_preview import umi_is_stranded_in_comment

        assert umi_is_stranded_in_comment(self.ENA_WITH_UMI) is True
        assert umi_is_stranded_in_comment(self.ENA_WITH_UMI, source="ena") is True

    def test_a_spaceless_ena_header_stays_safe(self):
        """With no accession prefix ENA has no comment field; only the fallback hides one."""
        from lib.sra_header_preview import umi_is_stranded_in_comment

        assert umi_is_stranded_in_comment(self.ORIGFMT_WITH_UMI, source="ena") is False

    def test_the_inspection_refuses_sra_direct_on_the_fallback_path(self):
        insp = inspection_from_header_records(
            {"SRR33628723": [self.ORIGFMT_WITH_UMI, "NAGCA", "+", "#AAFF"]},
            sources={"SRR33628723": "fastq-dump"},
        )
        assert insp.umi_in_comment is True
        assert "cannot be used" in insp.notes

    def test_without_sources_the_old_behaviour_stands(self):
        """With no provenance, a header is read as ENA's."""
        insp = inspection_from_header_records(
            {"SRR33628723": [self.ENA_WITH_UMI, "NAGCA", "+", "#AAFF"]})
        assert insp.umi_in_comment is True


class TestRecordsAreSplitByRole:
    """A record list is four lines per read; only every fourth is a header."""

    def test_headers_and_sequences(self):
        from lib.sra_header_preview import headers_of, sequences_of

        recs = ["@SRR1.1 1/1", "ACGT", "+", "@@@@", "@SRR1.2 2/1", "TTTT", "+", "FFFF"]
        assert headers_of(recs) == ["@SRR1.1 1/1", "@SRR1.2 2/1"]
        assert sequences_of(recs) == ["ACGT", "TTTT"]


class TestSraLoadFormat:
    """`vdb-dump --info` says whether a run was loaded from FASTQ or from an aligned BAM."""

    def _fake(self, monkeypatch, stdout=None, exc=None):
        import subprocess

        import lib.sra_header_preview as shp

        def run(*a, **k):
            if exc:
                raise exc
            return subprocess.CompletedProcess(a, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(shp.subprocess, "run", run)
        return shp

    def test_a_bam_load_is_reported(self, monkeypatch):
        shp = self._fake(monkeypatch, "acc    : SRR5646571\nFMT    : BAM\nLDR    : bam-load.2.8.2\n")
        assert shp.sra_load_format("SRR5646571") == "BAM"

    def test_a_fastq_load_is_reported(self, monkeypatch):
        shp = self._fake(monkeypatch, "FMT    : FASTQ\nLDR    : latf-load.2.9.7\n")
        assert shp.sra_load_format("SRR24067475") == "FASTQ"

    def test_a_missing_tool_is_unknown_not_an_error(self, monkeypatch):
        shp = self._fake(monkeypatch, exc=FileNotFoundError("vdb-dump"))
        assert shp.sra_load_format("SRR1") == ""
