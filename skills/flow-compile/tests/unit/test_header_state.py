"""Four header states, and the parameters each implies.

    execution param       actual header (RBP ENCODE project on Flow)
    encode_eclip=false    @HWI-D00611:153:…:25252 2:N:0:GAATTCGTTAATCTTA
    encode_eclip=true     @TAAAG:HWI-D00611:119:…:90397 2:N:0:TCCGGAGATATAGCCT

The second is `eclipdemux` output: a 5-nt randomer prepended to the read name (949 distinct
values across 5,371 reads). `inspect_header_lines` answers `(False, False)` for it and for a raw
header, and `(True, False)` for both `:rbc:` positions, so it cannot drive the parameters.

Story: FAILURES.md#eclip-header-states
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.header_state import (  # noqa: E402
    RANDOMER_PREFIX,
    RAW,
    RBC_END,
    RBC_MID,
    classify_header,
    classify_headers,
    params_for_state,
)

# Verbatim from the RBP ENCODE project on Flow.
ENCODE_PREPENDED = "@TAAAG:HWI-D00611:119:C6K7PANXX:4:1114:2885:90397 2:N:0:TCCGGAGATATAGCCT"
ENCODE_RAW = "@HWI-D00611:153:C6PBEANXX:5:2310:12664:25252 2:N:0:GAATTCGTTAATCTTA"
ENCODE_RBC_MID = "@HWI-D00611:1:1101:1445:2149:rbc:CACTTG 1:N:0:ATCACG"
ICLIP_RBC_END = "@SRR33628707.1_NS500784:933:H5W2CBGXN:1:11101:8436:10721:N:0:1rbc:AAAATATAA"


class TestTheStateTheDetectorCouldNotSee:
    def test_prepended_randomer_is_its_own_state(self):
        assert classify_header(ENCODE_PREPENDED) == RANDOMER_PREFIX

    def test_it_is_not_confused_with_raw(self):
        """`inspect_header_lines` gives (False, False) for both; the state must differ."""
        assert classify_header(ENCODE_PREPENDED) != classify_header(ENCODE_RAW)

    def test_raw_is_raw(self):
        assert classify_header(ENCODE_RAW) == RAW

    def test_a_prepended_randomer_must_not_be_re_extracted(self):
        """Re-extracting strips real insert bases and dedups on the wrong sequence."""
        params = params_for_state(RANDOMER_PREFIX, experimental_method="eCLIP")
        assert params["move_umi_to_header"] == "false"

    def test_the_live_encode_param_is_reproduced(self):
        """RBP ENCODE runs these with encode_eclip=true. Our derivation must agree."""
        params = params_for_state(RANDOMER_PREFIX, experimental_method="eCLIP")
        assert params["encode_eclip"] == "true"


class TestRbcPosition:
    def test_mid_header_is_encode_layout(self):
        assert classify_header(ENCODE_RBC_MID) == RBC_MID

    def test_end_of_header_is_not(self):
        assert classify_header(ICLIP_RBC_END) == RBC_END

    def test_the_two_are_distinguishable(self):
        """`inspect_header_lines` gives (True, False) for both; the state must differ."""
        assert classify_header(ENCODE_RBC_MID) != classify_header(ICLIP_RBC_END)

    def test_mid_header_must_not_set_encode_eclip(self):
        """`encode_moveumi` takes the first colon field of the read name as the UMI.

        On `@HWI-D00611:…:rbc:CACTTG` that field is the instrument name, so every read's UMI would be
        `HWI-D00611` and UMICollapse would collapse the library.

        Story: FAILURES.md#encode-moveumi
        """
        assert params_for_state(RBC_MID, experimental_method="eCLIP")["encode_eclip"] == "false"

    def test_end_of_header_does_not_even_for_eclip(self):
        """Position decides, not presence."""
        assert params_for_state(RBC_END, experimental_method="eCLIP")["encode_eclip"] == "false"

    def test_both_rbc_forms_keep_the_separator(self):
        for state in (RBC_MID, RBC_END):
            p = params_for_state(state, experimental_method="iCLIP")
            assert p["umi_separator"] == "rbc:"
            assert p["move_umi_to_header"] == "false"


class TestRaw:
    def test_raw_extracts(self):
        p = params_for_state(RAW, experimental_method="eCLIP")
        assert p["move_umi_to_header"] == "true"
        assert p["umi_separator"] == "_"

    def test_raw_is_never_encode_layout(self):
        assert params_for_state(RAW, experimental_method="eCLIP")["encode_eclip"] == "false"


class TestNonEclipNeverSetsEncodeEclip:
    def test_iclip_mid_header_rbc_is_still_false(self):
        """`encode_eclip` is an eCLIP-family setting; the assay gates it."""
        assert params_for_state(RANDOMER_PREFIX, experimental_method="iCLIP")["encode_eclip"] == "false"

    def test_seclip_counts_as_eclip_family(self):
        assert params_for_state(RANDOMER_PREFIX, experimental_method="seCLIP")["encode_eclip"] == "true"


class TestSampledHeaders:
    def test_a_consistent_sample_classifies(self):
        assert classify_headers([ENCODE_PREPENDED] * 5).state == RANDOMER_PREFIX

    def test_a_mixed_sample_is_refused_not_guessed(self):
        """Mixed states mean the files were not produced the same way; picking a majority
        would silently apply one file's params to another's reads."""
        result = classify_headers([ENCODE_PREPENDED, ENCODE_RAW])
        assert result.ok is False
        assert "mixed" in result.reason.lower()

    def test_an_empty_sample_is_not_raw(self):
        """No headers is no evidence; defaulting to RAW would extract from anything."""
        assert classify_headers([]).ok is False

    def test_a_consistent_sample_is_ok(self):
        assert classify_headers([ICLIP_RBC_END] * 3).ok is True


class TestTheEnaPrefixDoesNotHideTheState:
    """ENA renders `@<run>.<n> <original name>`; the state is in the original name."""

    def test_a_prepended_randomer_behind_the_accession_is_seen(self):
        from lib.header_state import RANDOMER_PREFIX, classify_header

        assert classify_header(
            "@SRR1.1 TAAAG:HWI-D00611:119:C6VM5ANXX:1:1101:1234:90397 2:N:0:TCCGG"
        ) == RANDOMER_PREFIX

    def test_a_plain_instrument_name_behind_the_accession_is_raw(self):
        from lib.header_state import RAW, classify_header

        assert classify_header("@SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1") == RAW
