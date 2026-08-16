"""Folding a UMI out of the header comment is only safe if the separator is unambiguous.

When a study's UMI sits in the FASTQ header *comment* (everything after the first space),
every aligner discards it — see ``reference/`` and the LARP6 write-up. The fix is to fold the
comment into the read name before upload, which ``removespace.py`` does by turning spaces and
slashes into underscores.

**That fix is safe only when the UMI separator occurs once.**

GSE297587 (LARP6) used ``umi_separator=rbc:``. ``rbc:`` appears exactly once, so "everything
after the separator" has one meaning and the trailing ``/1`` → ``_1`` rode along inside the
parsed UMI harmlessly — a constant suffix shifts every UMI identically and cannot change which
reads group together.

GSE159997 (CSDE1) carries a bare underscore field instead::

    @SRR12885981.1 D00733:360:CCM6UANXX:1:1102:1162:2364_CATGCCGGATAT/1
    →  @SRR12885981.1_D00733:360:CCM6UANXX:1:1102:1162:2364_CATGCCGGATAT_1

``umi_separator="_"`` now has four candidate split points, and a parser taking the **last**
field reads the UMI as ``1`` — identical for every read in the file. Dedup would collapse
every read at a crosslink position into one count. The run finishes green.

The check is deliberately empirical rather than a claim about any particular parser: **does
the field vary across reads?** A constant UMI is wrong under every convention, so this catches
the failure without needing to know which convention the tool follows.

**The fix** is to rewrite the header so the read name ends with the UMI and nothing follows
it (``@SRR12885981.1_CATGCCGGATAT``), which is unambiguous under either rule.

This module is pure; the caller supplies sampled header lines.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    """Would ``umi_separator`` extract a real UMI from these read names?

    Takes the LAST separator-delimited field, which is the pessimistic reading — if that
    field is a genuine UMI the extraction is safe under either convention, and if it is
    constant the run is silently wrong under at least one.
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
