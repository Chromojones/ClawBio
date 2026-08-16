"""`removespace.py` is only safe when the UMI separator appears ONCE in the read name.

GSE297587 (LARP6) folded its comment into the read name and used ``umi_separator=rbc:``.
That worked because ``rbc:`` occurs exactly once, so "everything after the separator" has
only one possible meaning and the trailing ``/1`` → ``_1`` rode along harmlessly.

GSE159997 (CSDE1) carries its UMI as a bare underscore field::

    @SRR12885981.1 D00733:360:CCM6UANXX:1:1102:1162:2364_CATGCCGGATAT/1

`removespace.py` turns spaces and slashes into underscores, giving::

    @SRR12885981.1_D00733:360:CCM6UANXX:1:1102:1162:2364_CATGCCGGATAT_1

Now ``umi_separator="_"`` has **four** candidate split points. A parser that takes the last
field reads the UMI as ``1`` — identical for every read in the file. Dedup would then collapse
every read at a crosslink position to a single count, silently, on a run that finishes green.

The check is deliberately empirical rather than a rule about parsers: **does the field the
parser would take actually vary across reads?** A constant UMI is wrong under every parsing
convention, so this catches the failure without needing to know which convention the tool uses.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.umi_header_safety import (  # noqa: E402
    check_umi_safety,
    fold_comment_into_name,
)

# Verbatim from GSE159997 (SRR12885981), five consecutive reads.
CSDE1_RAW = [
    "@SRR12885981.1 D00733:360:CCM6UANXX:1:1102:1162:2364_CATGCCGGATAT/1",
    "@SRR12885981.2 D00733:360:CCM6UANXX:1:1102:1138:2383_GAAGCCGGATTT/1",
    "@SRR12885981.3 D00733:360:CCM6UANXX:1:1102:1257:2387_AAGACCGGATTT/1",
    "@SRR12885981.4 D00733:360:CCM6UANXX:1:1102:1318:2479_TACACCGGATAT/1",
    "@SRR12885981.5 D00733:360:CCM6UANXX:1:1102:1562:2431_TCTCCCGGATAT/1",
]

# GSE297587 (LARP6) shape — a unique separator.
LARP6_RAW = [
    "@SRR33628723.1 NS500784:100:HXXXX:1:11101:1000:1000rbc:TAGGATAAA/1",
    "@SRR33628723.2 NS500784:100:HXXXX:1:11101:1001:1002rbc:CCGTATCGA/1",
    "@SRR33628723.3 NS500784:100:HXXXX:1:11101:1003:1004rbc:GGATCCTTA/1",
]


class TestTheLarp6ShapeStaysAllowed:
    """A unique separator is unambiguous — this path must keep working."""

    def test_rbc_separator_is_safe(self):
        folded = [fold_comment_into_name(h) for h in LARP6_RAW]
        result = check_umi_safety(folded, separator="rbc:")
        assert result.safe is True

    def test_the_parsed_umi_varies_across_reads(self):
        folded = [fold_comment_into_name(h) for h in LARP6_RAW]
        result = check_umi_safety(folded, separator="rbc:")
        assert result.distinct_values == 3


class TestTheCsde1Trap:
    """The GSE159997 regression — a green run that silently collapses everything."""

    def test_naive_removespace_output_is_refused(self):
        folded = [fold_comment_into_name(h) for h in CSDE1_RAW]
        result = check_umi_safety(folded, separator="_")
        assert result.safe is False

    def test_the_reason_names_the_constant_field_not_a_vague_failure(self):
        folded = [fold_comment_into_name(h) for h in CSDE1_RAW]
        result = check_umi_safety(folded, separator="_")
        assert result.distinct_values == 1
        assert "constant" in result.reason.lower()

    def test_the_ambiguity_itself_is_reported(self):
        """Four split points is a problem even before asking which one the tool picks."""
        folded = [fold_comment_into_name(h) for h in CSDE1_RAW]
        assert check_umi_safety(folded, separator="_").separator_count > 1

    def test_a_name_ending_in_the_real_umi_is_safe(self):
        """The fix: rewrite so the read name ends with the UMI and nothing follows it."""
        rewritten = [
            "@SRR12885981.1_CATGCCGGATAT",
            "@SRR12885981.2_GAAGCCGGATTT",
            "@SRR12885981.3_AAGACCGGATTT",
            "@SRR12885981.4_TACACCGGATAT",
            "@SRR12885981.5_TCTCCCGGATAT",
        ]
        result = check_umi_safety(rewritten, separator="_")
        assert result.safe is True
        assert result.separator_count == 1
        assert result.distinct_values == 5


class TestFoldingTheComment:
    def test_spaces_and_slashes_become_underscores(self):
        assert fold_comment_into_name("@a b/1") == "@a_b_1"

    def test_a_header_with_no_comment_is_unchanged(self):
        assert fold_comment_into_name("@SRR1.1") == "@SRR1.1"


class TestDegenerateInput:
    def test_a_separator_that_is_absent_is_refused(self):
        result = check_umi_safety(["@SRR1.1_AAAA", "@SRR1.2_CCCC"], separator="rbc:")
        assert result.safe is False
        assert "not present" in result.reason.lower()

    def test_no_headers_is_refused_rather_than_passing_vacuously(self):
        result = check_umi_safety([], separator="_")
        assert result.safe is False

    def test_a_umi_that_varies_but_only_barely_still_warns(self):
        """Two distinct values across many reads means the field is not a UMI."""
        headers = [f"@SRR1.{i}_{'AAAA' if i % 2 else 'CCCC'}" for i in range(40)]
        result = check_umi_safety(headers, separator="_")
        assert result.safe is False
        assert "2" in result.reason
