"""Base composition finds the barcode/UMI boundary. It does not find the UMI's last base.

Reading GSE131210 (easyCLIP) straight off the reads, per-position base composition on read 1
gave an apparently clean answer — deviation from an even 25% per base::

    pos  1- 6   74.5 74.8 74.9 74.6 74.8 74.6    fixed        -> 6-nt L5 barcode
    pos  7-12    4.9  3.1  3.5  4.0  4.3  2.8    uniform      -> UMI
    pos 13       7.9                             ?
    pos 14      21.1                             clearly biased

I called a 6-nt UMI and moved on. The authors' own pipeline says otherwise::

    L5_inline: BBBBBBNNNNNNN      # 6 barcode bases then 7 UMI bases, as sequenced in read 1
    L3_inline: BBB

and their `clip_adapters.py` takes the UMI as `seq1[6:13]` — seven bases, positions 7 to 13.

Position 13 *is* a UMI base. It reads as 7.9% off-even because the terminal N of a synthesized
oligo carries real coupling bias, which lands it between the ~4% of a clean random base and the
12–21% of genomic sequence. There is no threshold that separates "last UMI base" from "first
genomic base" on composition alone, because the two overlap.

Getting this wrong is quiet and costly: a UMI declared one base short leaves that base on the
insert, so every read starts with a semi-random base, the 5' end used for the crosslink
position is off by one, and deduplication collapses on a 6-mer key where the protocol built a
7-mer — merging distinct molecules. Nothing errors.

So the inference must return a **range** whenever the base after the uniform run is ambiguous,
and say plainly that only the study's own configuration settles it. `flow-compile` reads the
authors' pipeline config when one exists; composition is the cross-check, not the source.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.inline_layout import infer_inline_layout  # noqa: E402

# Measured on SRX5830818 read 1, 16,605 reads: max |pct - 25| across A/C/G/T per position.
GSE131210_R1 = [74.5, 74.8, 74.9, 74.6, 74.8, 74.6,
                4.9, 3.1, 3.5, 4.0, 4.3, 2.8,
                7.9,
                21.1, 15.8, 12.9, 12.4, 11.9]


class TestTheBarcode:
    def test_the_fixed_prefix_is_found(self):
        assert infer_inline_layout(GSE131210_R1).barcode_len == 6

    def test_the_barcode_is_not_ambiguous(self):
        """A fixed base is ~75% off even and a random one ~4% — no overlap, so this end
        of the structure really is decidable from composition."""
        assert infer_inline_layout(GSE131210_R1).barcode_certain is True


class TestTheUmiBoundaryIsARange:
    def test_the_authors_length_is_inside_the_range(self):
        layout = infer_inline_layout(GSE131210_R1)
        assert layout.umi_len_min <= 7 <= layout.umi_len_max

    def test_the_composition_only_answer_is_also_inside_it(self):
        """6 is what the uniform run alone supports; the range must not silently drop it."""
        layout = infer_inline_layout(GSE131210_R1)
        assert layout.umi_len_min == 6

    def test_it_is_reported_as_uncertain(self):
        assert infer_inline_layout(GSE131210_R1).umi_certain is False

    def test_it_refuses_to_publish_a_single_number(self):
        """A lone `umi_len` attribute would be read as settled and copied into the sheet."""
        assert not hasattr(infer_inline_layout(GSE131210_R1), "umi_len")

    def test_the_description_sends_the_reader_to_the_config(self):
        text = infer_inline_layout(GSE131210_R1).describe().lower()
        assert "6" in text and "7" in text
        assert "config" in text or "pipeline" in text


class TestAnUnambiguousLayout:
    def test_a_clean_jump_is_certain(self):
        """Uniform run straight into strong bias, no intermediate base."""
        layout = infer_inline_layout([74.0] * 4 + [3.0] * 8 + [22.0, 19.0, 18.0])
        assert layout.barcode_len == 4
        assert layout.umi_certain is True
        assert layout.umi_len_min == layout.umi_len_max == 8

    def test_no_fixed_prefix_is_handled(self):
        """Some protocols have a UMI and no in-line barcode at all."""
        layout = infer_inline_layout([3.5] * 10 + [20.0, 18.0])
        assert layout.barcode_len == 0
        assert layout.umi_len_min == 10

    def test_no_umi_is_handled(self):
        """Barcode straight into genomic — a pre-deduplicated or UMI-less library."""
        layout = infer_inline_layout([74.0] * 5 + [20.0, 18.0, 21.0])
        assert layout.barcode_len == 5
        assert layout.umi_len_max == 0
