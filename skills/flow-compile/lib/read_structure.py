"""Where the UMI is, how long it is, and whether the parameters can reach it. Pure.

Composition finds the barcode/UMI boundary but not the UMI's last base, so
`infer_inline_layout` returns a range; the length comes from the authors' pipeline config.
`classify_read_structure` says whether the deposited reads are untrimmed (one length, adapter
reading through) or processed before submission (varied lengths, no adapter), since a block
already cut off must not be cut off again.

Story: FAILURES.md#read-structure
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

#: Read-structure verdicts.
UNTRIMMED = "untrimmed"
PROCESSED = "processed"
UNCLEAR = "unclear"

#: 3' adapters by their first 13 bases, enough to be unambiguous and short enough to survive
#: a truncated read.
ADAPTERS = {
    "TruSeq/NEB 3'": "AGATCGGAAGAGCACACG",
    "iCLIP L3": "AGATCGGAAGAGCGGTTCAG",
    "TruSeq read 2": "AGATCGGAAGAGCGTCGTG",
    "TruSeq small RNA": "TGGAATTCTCGGGTGCCAAGG",
    "Nextera": "CTGTCTCTTATACACATCT",
}
#: CLIP inserts are short, so an untrimmed library shows its adapter in many reads.
ADAPTER_PRESENT_FRACTION = 0.02
ADAPTER_ABSENT_FRACTION = 0.005
#: A partial gzip fetch can cut the last record, so one length means nearly every read.
FIXED_LENGTH_FRACTION = 0.99

#: A position holding one base.
FIXED_MIN_PCT = 65.0
#: Below this a base is absent from a position; two absent bases mean a designed position.
ABSENT_MAX_PCT = 3.0
#: One base this rare, with the others present, is a design constraint leaking into an
#: otherwise ambiguous position.
LOW_MAX_PCT = 5.0


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

def base_profile(seqs: list[str], *, positions: int = 20) -> list[dict[str, float]]:
    """Percent A/C/G/T at each of the first `positions` positions; N and short reads are left
    out of a position's count.
    """
    profile = []
    for i in range(positions):
        counts = Counter(s[i] for s in seqs if len(s) > i and s[i] in "ACGT")
        total = sum(counts.values())
        profile.append({b: (100.0 * counts[b] / total if total else 0.0) for b in "ACGT"})
    return profile


def _position_class(pct: dict[str, float]) -> str:
    """F fixed, D designed (two bases absent), N random, n biased or ambiguous, - no data."""
    if not any(pct.values()):
        return "-"
    if max(pct.values()) >= FIXED_MIN_PCT:
        return "F"
    if sum(v < ABSENT_MAX_PCT for v in pct.values()) >= 2:
        return "D"
    if max(abs(v - 25.0) for v in pct.values()) <= UNIFORM_MAX_DEV:
        return "N"
    return "n"


@dataclass
class InlineBlock:
    """The 5' block to move into the header: everything up to the last designed position, plus
    any random run that follows it. The end is a range where a position is ambiguous.
    """

    block_len_min: int
    block_len_max: int
    designed_positions: list[int]
    pattern: str

    def describe(self) -> str:
        if not self.block_len_max:
            return f"no in-line block at the 5' end (positions read {self.pattern})."
        where = (f"designed base(s) at position(s) "
                 f"{', '.join(str(p) for p in self.designed_positions)}; "
                 if self.designed_positions else "")
        span = (f"{self.block_len_min} nt" if self.block_len_min == self.block_len_max
                else f"{self.block_len_min}-{self.block_len_max} nt")
        return (
            f"in-line block of {span} ({where}positions read {self.pattern}). Composition "
            f"cannot settle the last base: take the exact length from the authors' pipeline "
            f"config, and move the whole block, spacer included, or the crosslink site shifts."
        )


def infer_inline_block(profile: list[dict[str, float]]) -> InlineBlock:
    """The 5' block from a per-position base profile.

    Designed positions (one base, or two bases absent) can only be library structure, so the
    block runs to the last of them; a random run after that is a UMI and belongs to it. With no
    designed position, a leading random run is a UMI on its own. A single designed first base
    with nothing after it is truncation bias, not design.
    """
    classes = "".join(_position_class(p) for p in profile)
    designed = [i + 1 for i, c in enumerate(classes) if c in "FD"]
    if designed == [1]:
        designed = []
    end = designed[-1] if designed else 0
    while end < len(classes) and classes[end] == "N":
        end += 1
    if not designed and end and end < 2:
        end = 0
    block_min = end
    while (end < len(profile) and classes[end] == "n" and block_min
           and (max(abs(v - 25.0) for v in profile[end].values()) < GENOMIC_MIN_DEV
                or any(v < LOW_MAX_PCT for v in profile[end].values()))):
        end += 1
    return InlineBlock(block_min, end, designed, classes)


@dataclass
class ReadStructure:
    """What the deposited reads look like, and the verdict that follows."""

    verdict: str
    read_count: int
    fixed_length: int
    lengths: dict[int, int]
    adapter: str
    adapter_fraction: float
    load_format: str
    block: InlineBlock
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict, "read_count": self.read_count,
            "fixed_length": self.fixed_length, "lengths": dict(self.lengths),
            "adapter": self.adapter, "adapter_fraction": round(self.adapter_fraction, 4),
            "load_format": self.load_format,
            "block_len_min": self.block.block_len_min, "block_len_max": self.block.block_len_max,
            "positions": self.block.pattern, "reasons": self.reasons,
        }

    def describe(self) -> str:
        head = f"{self.verdict} ({self.read_count} reads): " + "; ".join(self.reasons)
        if self.verdict == UNTRIMMED:
            return head + ". " + self.block.describe()
        if self.verdict == PROCESSED:
            return head + ". Nothing to extract; without a UMI in the header there is nothing to deduplicate on."
        return head + ". Ask the authors how the reads were prepared before choosing parameters."


def classify_read_structure(seqs: list[str], *, load_format: str = "") -> ReadStructure:
    """Untrimmed, processed, or unclear, from the read lengths, the 3' adapter, and how SRA
    loaded the run.
    """
    seqs = [s for s in seqs if s]
    lengths = Counter(len(s) for s in seqs)
    top_len, top_n = lengths.most_common(1)[0] if lengths else (0, 0)
    fixed = top_len if seqs and top_n >= FIXED_LENGTH_FRACTION * len(seqs) else 0
    fraction, adapter = 0.0, ""
    for name, seq in ADAPTERS.items():
        hit = sum(seq[:13] in s for s in seqs) / len(seqs) if seqs else 0.0
        if hit > fraction:
            fraction, adapter = hit, name
    present = fraction >= ADAPTER_PRESENT_FRACTION
    absent = fraction < ADAPTER_ABSENT_FRACTION
    if not present:
        adapter = ""
    block = infer_inline_block(base_profile(seqs))

    reasons = []
    if not seqs:
        verdict = UNCLEAR
        reasons.append("no reads sampled")
    else:
        reasons.append(f"one length, {fixed} nt" if fixed
                       else f"{len(lengths)} lengths, {min(lengths)}-{max(lengths)} nt")
        reasons.append(f"{adapter} adapter in {100 * fraction:.0f}% of reads" if present
                       else "no adapter in the reads")
        if load_format:
            reasons.append(f"loaded into SRA from {load_format}")
        if load_format.upper() == "BAM" and not present:
            verdict = PROCESSED
        elif fixed and present:
            verdict = UNTRIMMED
        elif not fixed and absent:
            verdict = PROCESSED
        else:
            verdict = UNCLEAR
            reasons.append("one length with no adapter can be an extraction tool's cut"
                           if fixed else "adapter present but lengths vary")
    return ReadStructure(verdict, len(seqs), fixed, dict(lengths.most_common(6)),
                         adapter, fraction, load_format, block, reasons)


@dataclass
class UmiParamCheck:
    ok: bool
    reason: str = ""


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def check_umi_params(params: dict, *, barcode: str = "") -> UmiParamCheck:
    """Check the UMI params agree with each other and, when given, with the barcode: the
    `umi_header_format` mask must be all-N of the barcode's length.
    """
    move = _truthy(params.get("move_umi_to_header"))
    skip = _truthy(params.get("skip_umi_dedupe"))
    separator = str(params.get("umi_separator") or "").strip()
    fmt = str(params.get("umi_header_format") or "").strip()

    if not skip and not separator:
        where = "extracted into the read name" if move else "already in the read name"
        return UmiParamCheck(
            False,
            f"deduplication is on but `umi_separator` is absent. The UMI is {where}, and "
            f"UMICollapse has no delimiter to find it with — it dies with "
            f"`IllegalStateException: No match found` at SAMRead.getUMI, after mapping. "
            f"Set umi_separator (`_` for extracted barcodes, `rbc:` for iCount/ultraplex "
            f"headers), or set skip_umi_dedupe=true if there is genuinely no UMI.",
        )

    if move:
        if not fmt:
            return UmiParamCheck(
                False,
                "`move_umi_to_header=true` needs `umi_header_format` — the mask that says "
                "how many bases to carve off the read.",
            )
        if set(fmt.upper()) != {"N"}:
            return UmiParamCheck(
                False,
                f"`umi_header_format` must be all-N of the barcode's length, not {fmt!r}. "
                f"The metadata field carries the real sequence; the execution mask does not.",
            )
        if barcode and len(barcode.strip()) != len(fmt):
            return UmiParamCheck(
                False,
                f"barcode is {len(barcode.strip())} nt ({barcode.strip()}) but "
                f"`umi_header_format` is {len(fmt)} — the wrong number of bases would be "
                f"taken off every read.",
            )

    return UmiParamCheck(True)


