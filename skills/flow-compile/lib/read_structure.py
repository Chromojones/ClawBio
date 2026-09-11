"""Where the UMI is, how long it is, and whether the parameters can reach it. Pure.

Composition finds the barcode/UMI boundary but not the UMI's last base, so
`infer_inline_layout` returns a range; the length comes from the authors' pipeline config.

Story: FAILURES.md#read-structure
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.results import ERROR, Finding as Check, INFO, Verdict, WARNING  # noqa: F401

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

#: Below this many distinct values, a field is a label, not a UMI. Two barcodes across
#: thousands of reads is a multiplex tag; a real UMI has hundreds of distinct values.
_MIN_DISTINCT = 3


@dataclass
class UmiSafety:
    """Whether the parsed UMI field can be trusted."""

    safe: bool
    separator_count: int = 0
    distinct_values: int = 0
    reason: str = ""


def fold_comment_into_name(header: str) -> str:
    """What ``removespace.py`` does: spaces and slashes become underscores."""
    return header.replace(" ", "_").replace("/", "_")


def check_umi_safety(headers: list[str], *, separator: str) -> UmiSafety:
    """Would `umi_separator` extract a real UMI from these read names? Reads the last
    separator-delimited field; a constant one is a label, not a UMI.
    """
    names = [h.lstrip("@").split()[0] for h in headers if h.strip()]
    if not names:
        return UmiSafety(safe=False, reason="no headers sampled — nothing was verified")

    counts = [n.count(separator) for n in names]
    if not any(counts):
        return UmiSafety(
            safe=False, separator_count=0,
            reason=f"separator {separator!r} is not present in the read name",
        )

    tails = [n.rsplit(separator, 1)[-1] for n in names]
    distinct = len(set(tails))
    max_count = max(counts)

    if distinct < _MIN_DISTINCT:
        detail = (
            "constant across every read" if distinct == 1
            else f"only {distinct} distinct values across {len(names)} reads"
        )
        return UmiSafety(
            safe=False, separator_count=max_count, distinct_values=distinct,
            reason=(
                f"the field after the last {separator!r} is {detail} — this is a label, not a "
                f"UMI. Deduplication would collapse every read at a position into one count, "
                f"silently, on a run that finishes green. Rewrite the header so the read name "
                f"ENDS with the UMI."
            ),
        )

    if max_count > 1:
        return UmiSafety(
            safe=True, separator_count=max_count, distinct_values=distinct,
            reason=(
                f"{separator!r} occurs up to {max_count} times, but the trailing field varies "
                f"({distinct} distinct) so the extraction resolves — still prefer a header "
                f"ending in the UMI."
            ),
        )

    return UmiSafety(safe=True, separator_count=max_count, distinct_values=distinct)
