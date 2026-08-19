"""Where does the in-line barcode end, the UMI end, and the insert begin?

Read a CLIP library's read 1 and compute, per position, how far the base composition departs
from an even 25% per base. Fixed bases sit near 75. Random bases sit near 0. The structure
appears to fall out of the numbers.

On GSE131210 (easyCLIP) it appeared to::

    pos  1- 6   74.5 74.8 74.9 74.6 74.8 74.6    fixed
    pos  7-12    4.9  3.1  3.5  4.0  4.3  2.8    uniform
    pos 13       7.9                             ?
    pos 14      21.1                             biased

which reads as a 6-nt barcode and a 6-nt UMI. The authors' own pipeline says::

    L5_inline: BBBBBBNNNNNNN     # 6 barcode bases then 7 UMI bases, as sequenced in read 1

and their ``clip_adapters.py`` slices the UMI as ``seq1[6:13]`` — seven bases. Position 13 is
a UMI base. It measures 7.9 because the terminal N of a synthesized oligo carries real coupling
bias, putting it between a clean random base (~4) and genomic sequence (~12–21).

**Those two populations overlap, so no threshold separates them.** The last UMI base and the
first insert base are not distinguishable by composition, and a method that returns one number
is guessing at exactly the position where guessing is invisible.

Getting it wrong is silent and expensive. A UMI called one base short leaves that base on the
insert: every read then begins with a semi-random base, the 5' end used to place the crosslink
is off by one, and deduplication keys on a 6-mer where the protocol built a 7-mer, merging
molecules that were distinct. Nothing raises an error.

So this returns a **range** whenever the base after the uniform run is ambiguous, and never a
bare ``umi_len``. The study's own pipeline configuration is the source; this is the cross-check.

Pure — the caller supplies the per-position deviations.
"""

from __future__ import annotations

from dataclasses import dataclass

#: At or above this deviation from an even 25%, a position is a fixed base (barcode).
FIXED_MIN_DEV = 40.0

#: At or below this, a position is cleanly random (UMI).
UNIFORM_MAX_DEV = 6.0

#: At or above this, a position carries the compositional bias of real sequence (insert).
#: Between `UNIFORM_MAX_DEV` and this lies the ambiguous band, where a terminal UMI base and
#: a first insert base are indistinguishable.
GENOMIC_MIN_DEV = 10.0


@dataclass
class InlineLayout:
    """The read's leading structure. Deliberately has no single ``umi_len``."""

    barcode_len: int
    umi_len_min: int
    umi_len_max: int
    barcode_certain: bool
    umi_certain: bool
    ambiguous_positions: list[int]

    def describe(self) -> str:
        lines = [f"in-line barcode: {self.barcode_len} nt"
                 + ("" if self.barcode_certain else "  (UNCERTAIN)")]
        if self.umi_certain:
            lines.append(f"UMI: {self.umi_len_min} nt")
            lines.append(
                f"total to trim: {self.barcode_len + self.umi_len_min} nt"
            )
            return "\n".join(lines)
        lines.append(
            f"UMI: {self.umi_len_min}-{self.umi_len_max} nt — NOT decidable from composition."
        )
        lines.append(
            f"  position(s) {', '.join(str(p) for p in self.ambiguous_positions)} sit between "
            f"a clean random base and real sequence. The terminal base of a synthesized UMI "
            f"carries coupling bias, so it looks partly biased; a first insert base can look "
            f"partly random. The two overlap."
        )
        lines.append(
            "  Settle it from the study's own pipeline config (e.g. an `L5_inline` pattern of "
            "B and N characters, or the slice used by their trimming script), not from these "
            "numbers. A UMI one base short shifts the crosslink position by one and dedups on "
            "a shorter key — neither of which errors."
        )
        return "\n".join(lines)


def infer_inline_layout(
    deviations: list[float],
    *,
    fixed_min_dev: float = FIXED_MIN_DEV,
    uniform_max_dev: float = UNIFORM_MAX_DEV,
    genomic_min_dev: float = GENOMIC_MIN_DEV,
) -> InlineLayout:
    """Infer the leading structure from per-position deviation from even base composition.

    ``deviations[i]`` is ``max(|pct(base) - 25|)`` over A/C/G/T at position ``i+1``.
    """
    n = len(deviations)

    barcode_len = 0
    while barcode_len < n and deviations[barcode_len] >= fixed_min_dev:
        barcode_len += 1

    # The run of unambiguously random bases immediately after the barcode.
    i = barcode_len
    while i < n and deviations[i] <= uniform_max_dev:
        i += 1
    umi_len_min = i - barcode_len

    # Then any bases in the ambiguous band — each could be a terminal UMI base or the
    # first insert base, and composition cannot tell which.
    ambiguous: list[int] = []
    j = i
    while j < n and deviations[j] < genomic_min_dev:
        ambiguous.append(j + 1)
        j += 1
    umi_len_max = j - barcode_len

    return InlineLayout(
        barcode_len=barcode_len,
        umi_len_min=umi_len_min,
        umi_len_max=umi_len_max,
        barcode_certain=all(
            d >= fixed_min_dev or d <= uniform_max_dev for d in deviations[:barcode_len + 1]
        ) if barcode_len else True,
        umi_certain=not ambiguous,
        ambiguous_positions=ambiguous,
    )
