"""`move_umi_to_header=true` without `umi_separator` kills UMICollapse.

Four consecutive studies — GSE75418, GSE68800, GSE80202, GSE58448 — were submitted with::

    {"move_umi_to_header": "true", "umi_header_format": "NNNNNNNNN",
     "skip_umi_dedupe": "false", "crosslink_position": "start", "encode_eclip": "false"}

and no `umi_separator`. The pipeline extracts the barcode and writes it into the read name,
but UMICollapse is then told nothing about how to find it again, and dies::

    java.lang.IllegalStateException: No match found
        at umicollapse.util.SAMRead.getUMI(SAMRead.java:36)

E-MTAB-2700, which completed 605/605, carries the same shape **plus** `"umi_separator": "_"`.

The failure is loud but late: it arrives after trimming, mapping and sorting, so a 7-sample
study burns most of a run before anything says so. And because the exception names
`SAMRead.getUMI` rather than a parameter, it reads as a UMI-in-the-data problem — the same
trap as the LARP6 header case, which produces a byte-identical stack trace for an entirely
different reason.

These params are checkable before submitting: they are internally inconsistent on their own,
without reference to the reads.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.read_structure import check_umi_params  # noqa: E402

WORKING = {  # E-MTAB-2700, 605/605
    "move_umi_to_header": "true", "umi_separator": "_",
    "umi_header_format": "NNNNNNNNN", "skip_umi_dedupe": "false",
    "crosslink_position": "start", "encode_eclip": "false",
}


class TestTheFourStudyRegression:
    def test_extraction_without_a_separator_is_refused(self):
        params = {k: v for k, v in WORKING.items() if k != "umi_separator"}
        result = check_umi_params(params)
        assert result.ok is False
        assert "umi_separator" in result.reason

    def test_the_reason_names_the_consequence(self):
        params = {k: v for k, v in WORKING.items() if k != "umi_separator"}
        assert "umicollapse" in check_umi_params(params).reason.lower()

    def test_the_working_shape_passes(self):
        assert check_umi_params(WORKING).ok is True

    def test_an_empty_separator_counts_as_absent(self):
        assert check_umi_params({**WORKING, "umi_separator": ""}).ok is False


class TestOtherArchetypes:
    def test_umi_already_in_the_name_needs_a_separator_too(self):
        """LARP6/ultraplex: move_umi_to_header=false, separator rbc:."""
        params = {"move_umi_to_header": "false", "umi_separator": "rbc:",
                  "skip_umi_dedupe": "false", "crosslink_position": "start"}
        assert check_umi_params(params).ok is True

    def test_no_separator_when_dedup_runs_is_refused_whichever_archetype(self):
        params = {"move_umi_to_header": "false", "skip_umi_dedupe": "false",
                  "crosslink_position": "start"}
        assert check_umi_params(params).ok is False

    def test_skipping_dedup_needs_no_separator(self):
        """GSE76475 / the 17 headerless LIN28A: nothing to deduplicate."""
        params = {"move_umi_to_header": "false", "skip_umi_dedupe": "true",
                  "crosslink_position": "start"}
        assert check_umi_params(params).ok is True


class TestHeaderFormatCoherence:
    def test_extraction_requires_a_header_format(self):
        params = {k: v for k, v in WORKING.items() if k != "umi_header_format"}
        result = check_umi_params(params)
        assert result.ok is False
        assert "umi_header_format" in result.reason

    def test_header_format_must_be_all_n(self):
        result = check_umi_params({**WORKING, "umi_header_format": "NNNCAATNN"})
        assert result.ok is False
        assert "all-N" in result.reason

    def test_a_barcode_length_mismatch_is_reported(self):
        result = check_umi_params({**WORKING, "umi_header_format": "NNNNNNN"},
                                  barcode="NNNCAATNN")
        assert result.ok is False
        assert "9" in result.reason and "7" in result.reason

    def test_matching_lengths_pass(self):
        assert check_umi_params(WORKING, barcode="NNNCAATNN").ok is True
