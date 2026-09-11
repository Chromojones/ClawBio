"""Base composition finds the barcode/UMI boundary, not the UMI's last base.

GSE131210 read 1, deviation from an even 25% per base::

    pos  1- 6   74.5 74.8 74.9 74.6 74.8 74.6    fixed        -> 6-nt barcode
    pos  7-12    4.9  3.1  3.5  4.0  4.3  2.8    uniform      -> UMI
    pos 13       7.9                             ?
    pos 14      21.1                             biased

The authors' config (`L5_inline: BBBBBBNNNNNNN`) makes position 13 a UMI base: the terminal N of a
synthesized oligo carries coupling bias. A UMI one base short shifts the crosslink position and
deduplicates on the wrong key, so the inference returns a range and the length comes from the
authors' config.

Story: FAILURES.md#read-structure
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.read_structure import infer_inline_layout  # noqa: E402

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
