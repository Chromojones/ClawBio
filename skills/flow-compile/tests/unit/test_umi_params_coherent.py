"""`move_umi_to_header=true` needs `umi_separator`, or UMICollapse fails.

UMICollapse otherwise dies with `IllegalStateException: No match found` at `SAMRead.getUMI`,
after trimming, mapping and sorting (GSE75418, GSE68800, GSE80202, GSE58448). The params are
inconsistent on their own, so they are checked before submission.

Story: FAILURES.md#read-structure
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
