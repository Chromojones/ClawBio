"""Tests for the remote FASTQ header preview (gates `flowbio samples import`).

ENA renders `@<run>.<n> <original spot name>`, which is the form Flow itself fetches — the
preview must see the study exactly as the import will, so ENA is the primary path.

`fastq-dump` does NOT rewrite deflines to `@SRR…N`, and `:rbc:` survives every dump form
(measured, sra-tools 3.2.1). The UMI is lost at the whitespace boundary instead: the SAM
QNAME ends at the first space. The fallback stays distrusted for the inverse reason —
`--origfmt` removes the comment field the check reads. See the class at the foot of this
file.
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.sra_header_preview import (  # noqa: E402
    inspection_from_header_records,
    parse_ena_fastq_urls,
    preview_to_headers_text,
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
        """Regression: the ftp path must be located by content, not by field index."""
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

    def test_headers_text_round_trips(self):
        text = preview_to_headers_text({"SRR21863801": ECLIP_RECORDS})
        assert "@SRR21863801.1" in text
        assert text.endswith("\n")

    def test_empty_preview_is_safe(self):
        inspection = inspection_from_header_records({})
        assert inspection.has_rbc is False
        assert inspection.sample_headers == []


class TestUmiInHeaderBlocksSraDirect:
    """A UMI already in the header cannot survive SRA-direct import.

    ENA's defline prepends `<run>.<n> `, pushing the ORIGINAL header — which carries the
    `rbc:` UMI — into the comment field. Aligners drop the comment, so the BAM read name has
    no UMI and UMICollapse fails with `No match found` (GSE297587, execution
    971697795553261239). The preview sees these headers, so it must refuse the path up front
    rather than let the study reach a failed execution.
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
    """`fastq-dump --origfmt` erases the very whitespace the comment check reads.

    Measured on SRR33628723 (sra-tools 3.2.1), the same run as the UMI-in-comment case above:

        ENA fastq_ftp         @SRR33628723.1 NS500784:…:1rbc:TAGGATAAA/1   UMI in the comment
        fastq-dump (default)  @SRR33628723.1 NS500784:…:1rbc:TAGGATAAA length=83   same
        fastq-dump --origfmt  @NS500784:…:1rbc:TAGGATAAA                  no space at all

    The old docstring blamed `fastq-dump` for rewriting deflines to `@SRR…N` and destroying
    `:rbc:` — it does neither; `:rbc:` is present in all three. The real hazard is the
    opposite: `--origfmt` prints the original spot name ALONE, so the comment field does not
    exist, `umi_is_stranded_in_comment` sees no space, and the refusal that blocks SRA-direct
    silently disappears. The study then reaches the execution that dies at UMICollapse.

    The verdict is still decidable, because the rendering is deterministic: ENA and Flow fetch
    `@<run>.<n> <spot name>`, so whatever `--origfmt` shows in the name becomes the comment.
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
        """Without the accession prefix ENA genuinely has no comment; only the fallback lies."""
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
        """Callers that pass no provenance are assumed to be on the ENA path."""
        insp = inspection_from_header_records(
            {"SRR33628723": [self.ENA_WITH_UMI, "NAGCA", "+", "#AAFF"]})
        assert insp.umi_in_comment is True
