"""Four header states, not two booleans — and the one the detector could not see.

`fastq_headers.inspect_header_lines()` returns `(has_rbc, barcode_in_header)`. Two booleans
cannot express the four states an eCLIP FASTQ actually arrives in, and the gap is not
cosmetic. Measured against the RBP ENCODE project on Flow:

    execution param            actual header
    encode_eclip=false         @HWI-D00611:153:…:25252 2:N:0:GAATTCGTTAATCTTA
    encode_eclip=true          @TAAAG:HWI-D00611:119:…:90397 2:N:0:TCCGGAGATATAGCCT

The second is `eclipdemux` output: the randomer is **prepended to the title**. Verified as a
randomer and not a fixed barcode — 5 nt, **949 distinct values across 5,371 reads**, with
near-uniform base composition (deviation from 25% of 3.1–15.2 per position).

`inspect_header_lines` returns `(False, False)` for it — **the same answer it gives for a raw
header**. So a derivation trusting it sets `move_umi_to_header=true` and re-extracts five bases
from a read whose randomer has already been moved to the header: five real bases of insert are
stripped, and deduplication then keys on sequence that is not the UMI. Nothing errors.

It also returns `(True, False)` for **both** `:rbc:` forms, so the mid-header versus
end-of-header distinction that `reference/eclip-analysis-params.md` calls decisive for
`encode_eclip` cannot be derived from it either.

Both reference documents are wrong in the same direction. `SKILL.md` said "eCLIP + `:rbc:` →
`encode_eclip=true`", ignoring position. `reference/eclip-analysis-params.md` corrected that
but added "Never set `encode_eclip=true` without `:rbc:` in sampled headers" — which the live
ENCODE data contradicts, because the portal's own files carry a prepended randomer and no
`:rbc:` at all.

Story: FAILURES.md#eclip-header-states
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
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
        """`inspect_header_lines` returned (False, False) for both. That is the bug."""
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
        """`inspect_header_lines` returned (True, False) for both."""
        assert classify_header(ENCODE_RBC_MID) != classify_header(ICLIP_RBC_END)

    def test_mid_header_sets_encode_eclip(self):
        assert params_for_state(RBC_MID, experimental_method="eCLIP")["encode_eclip"] == "true"

    def test_end_of_header_does_not_even_for_eclip(self):
        """Position decides, not presence. This is the SKILL.md error."""
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
        assert params_for_state(RBC_MID, experimental_method="iCLIP")["encode_eclip"] == "false"

    def test_seclip_counts_as_eclip_family(self):
        assert params_for_state(RBC_MID, experimental_method="seCLIP")["encode_eclip"] == "true"


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
