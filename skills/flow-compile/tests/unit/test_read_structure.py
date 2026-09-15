"""Are the deposited reads untrimmed or processed, and where does the in-line block end?

Two runs settle the shapes. SRR24067475 (GSE228970): every read 50 nt, the TruSeq adapter
reading through, and an 11–12 nt block at the 5' end whose positions 9–11 hold only A/T.
SRR5646571 (GSE99688): lengths 15–59, no adapter, submitted as an aligned BAM of reads the
authors had already trimmed of their barcode — so there is nothing to extract and no UMI to
deduplicate on.

Story: FAILURES.md#read-structure
"""

import random
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.read_structure import (  # noqa: E402
    PROCESSED,
    UNCLEAR,
    UNTRIMMED,
    base_profile,
    classify_read_structure,
    infer_inline_block,
)

ADAPTER = "AGATCGGAAGAGCACACGTCTGAACTCCAGTCAC"


def _p(a, c, g, t):
    return {"A": a, "C": c, "G": g, "T": t}


#: SRR24067475, 194,353 reads: percent A C G T per position.
GSE228970 = [
    _p(20.7, 20.7, 20.1, 38.5), _p(21.2, 20.2, 22.8, 35.7), _p(20.5, 21.9, 21.6, 36.1),
    _p(21.2, 20.3, 22.6, 35.9), _p(22.8, 19.4, 22.0, 35.9), _p(23.2, 19.1, 22.7, 34.9),
    _p(25.1, 18.6, 21.9, 34.4), _p(26.4, 19.0, 21.5, 33.0),
    _p(46.0, 0.7, 0.8, 52.5), _p(48.5, 0.8, 1.1, 49.7), _p(12.6, 1.0, 1.0, 85.3),
    _p(31.6, 7.9, 3.1, 57.4),
    _p(16.1, 31.9, 9.5, 42.5), _p(22.7, 17.4, 36.4, 23.5), _p(23.4, 16.8, 31.6, 28.2),
    _p(21.7, 27.8, 32.2, 18.2),
]

#: The Koenig NNN-XXXX-NN layout (barcode ATCG), then insert.
KOENIG = [_p(26, 24, 25, 25)] * 3 + [_p(98, 1, 0.5, 0.5), _p(0.5, 98, 1, 0.5),
                                      _p(0.5, 0.5, 98, 1), _p(1, 0.5, 0.5, 98)] \
    + [_p(25, 24, 26, 25)] * 2 + [_p(20, 18, 24, 38), _p(22, 17, 26, 35)]

#: GSE131210: six fixed, seven random with a biased terminal N, then insert.
GSE131210 = [_p(0.2, 0.2, 0.1, 99.5)] * 6 + [_p(24, 26, 25, 25)] * 6 \
    + [_p(22, 24, 21, 33)] + [_p(15, 20, 45, 20), _p(20, 40, 25, 15)]

#: SRR5646571: the iCLIP crosslink T-bias at position 1, then genomic sequence.
CROSSLINK_ONLY = [_p(14.3, 12.7, 8.3, 64.6), _p(15.0, 21.9, 12.2, 50.9), _p(19.8, 20.2, 22.9, 37.1),
                  _p(23.3, 17.5, 20.1, 39.1), _p(20.3, 27.5, 22.3, 29.9), _p(20.0, 24.3, 21.1, 34.6)]


def _untrimmed_reads(n=400, seed=1):
    """50-nt reads: 8 T-biased variable bases, `WWT` spacer, a short insert, the adapter."""
    rng = random.Random(seed)
    reads = []
    for _ in range(n):
        umi = "".join(rng.choices("ACGT", weights=[2, 2, 2, 4], k=8))
        spacer = "".join(rng.choice("AT") for _ in range(2)) + "T"
        # genomic-like: 12-20% off even, never uniform
        insert = "".join(rng.choices("ACGT", weights=[3, 1, 1, 3], k=rng.randint(10, 30)))
        reads.append((umi + spacer + insert + ADAPTER + "ATCACGATCGCG")[:50])
    return reads


def _processed_reads(n=400, seed=2):
    rng = random.Random(seed)
    return ["".join(rng.choices("ACGT", k=rng.randint(15, 59))) for _ in range(n)]


class TestBaseProfile:
    def test_percentages_per_position(self):
        prof = base_profile(["AAAA", "AACC", "AGCC", "TTTT"], positions=4)
        assert prof[0] == _p(75.0, 0.0, 0.0, 25.0)
        assert prof[3] == _p(25.0, 50.0, 0.0, 25.0)

    def test_short_reads_and_n_are_left_out(self):
        prof = base_profile(["AN", "A"], positions=2)
        assert prof[0]["A"] == 100.0
        assert sum(prof[1].values()) == 0


class TestTheInlineBlock:
    def test_gse228970_is_eleven_to_twelve(self):
        """Positions 9–11 hold only A/T: designed. The eight before them belong to the block."""
        block = infer_inline_block(GSE228970)
        assert (block.block_len_min, block.block_len_max) == (11, 12)
        assert block.designed_positions == [9, 10, 11]

    def test_a_barcode_followed_by_a_umi_includes_the_umi(self):
        block = infer_inline_block(KOENIG)
        assert (block.block_len_min, block.block_len_max) == (9, 9)

    def test_gse131210_keeps_its_ambiguous_last_base(self):
        block = infer_inline_block(GSE131210)
        assert (block.block_len_min, block.block_len_max) == (12, 13)

    def test_the_crosslink_bias_alone_is_not_a_block(self):
        block = infer_inline_block(CROSSLINK_ONLY)
        assert (block.block_len_min, block.block_len_max) == (0, 0)

    def test_a_lone_designed_first_base_is_not_a_block(self):
        """A 68% T at position 1 with genomic sequence after it is truncation bias, not design."""
        block = infer_inline_block([_p(12, 12, 8, 68)] + [_p(22, 24, 21, 33)] * 8)
        assert block.block_len_max == 0

    def test_a_umi_with_no_barcode_is_a_block(self):
        block = infer_inline_block([_p(25, 25, 25, 25)] * 5 + [_p(20, 18, 24, 38)] * 6)
        assert (block.block_len_min, block.block_len_max) == (5, 5)

    def test_the_description_names_the_ambiguity(self):
        text = infer_inline_block(GSE228970).describe()
        assert "11" in text and "12" in text
        assert "config" in text.lower()


class TestTheVerdict:
    def test_one_length_with_the_adapter_is_untrimmed(self):
        s = classify_read_structure(_untrimmed_reads())
        assert s.verdict == UNTRIMMED
        assert s.fixed_length == 50
        assert s.adapter and s.adapter_fraction > 0.5
        assert s.block.block_len_min == 11

    def test_varied_lengths_without_the_adapter_is_processed(self):
        s = classify_read_structure(_processed_reads())
        assert s.verdict == PROCESSED
        assert s.fixed_length == 0
        assert s.adapter == ""

    def test_a_bam_load_is_processed_even_at_one_length(self):
        """A BAM holds reads that went through a pipeline; an aligned length is not a cycle count."""
        reads = ["".join(random.Random(i).choices("ACGT", k=41)) for i in range(300)]
        assert classify_read_structure(reads, load_format="BAM").verdict == PROCESSED
        assert "BAM" in classify_read_structure(reads, load_format="BAM").describe()

    def test_one_length_without_the_adapter_is_unclear(self):
        """An extraction tool cuts a fixed number of bases, so one short length proves nothing."""
        reads = ["".join(random.Random(i).choices("ACGT", k=41)) for i in range(300)]
        assert classify_read_structure(reads).verdict == UNCLEAR

    def test_varied_lengths_with_the_adapter_is_unclear(self):
        reads = [r[:random.Random(i).randint(35, 50)] for i, r in enumerate(_untrimmed_reads())]
        assert classify_read_structure(reads).verdict == UNCLEAR

    def test_no_reads_is_unclear_not_untrimmed(self):
        assert classify_read_structure([]).verdict == UNCLEAR

    def test_one_truncated_last_read_does_not_break_a_fixed_length(self):
        """A partial gzip fetch can cut the final record mid-sequence."""
        reads = _untrimmed_reads() + ["ACGTACGTAC"]
        assert classify_read_structure(reads).fixed_length == 50

    def test_the_description_states_what_it_measured(self):
        text = classify_read_structure(_untrimmed_reads()).describe()
        assert "50" in text and "adapter" in text.lower() and "11" in text
        text = classify_read_structure(_processed_reads()).describe()
        assert "processed" in text.lower() and "no adapter" in text.lower()
