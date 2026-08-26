"""Close the gaps `samples import` leaves, and refuse to call it done on the writer's word.

Every SRA-direct study needs the same fix-up: ``samples import`` accepts
``purification_target__annotation`` and ``source__annotation``, stores neither, and attaches no
project. :mod:`lib.import_verify` finds those gaps. This turns them into edits and, more
importantly, decides when the repair is actually finished.

That second job is the point. On GSE131210 a 34-sample repair loop died at sample 11 with::

    urllib.error.URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>

leaving 11 samples correct and 23 untouched, and nothing reported it. The loop had tracked its
own progress, so "wrote 11 edits" was the only evidence available and it reads as success. It
is the third transient disconnect in the log, so this is an ordinary event.

Two rules, both about not trusting the writer:

1. **Completion is measured by re-reading every sample.** Edits issued is not evidence —
   :func:`summarise_repair` takes ``edits_applied`` only to ignore it.
2. **The plan is rebuilt from observed state**, so a resumed run converges: samples already
   correct produce no edit, and a half-repaired study plans only its remainder.

Pure — the caller performs the reads and the writes.
"""

from __future__ import annotations
from lib.flow_client import project_id_of

from dataclasses import dataclass, field

#: Sheet columns that are not sample metadata and are never repaired.
_NON_METADATA = frozenset({"accession", "sample_type", "name", "organism"})

#: Suffix marking a column that lives as the ``annotation`` of its parent attribute rather
#: than as a metadata key of its own — the pair the import silently discards.
_ANNOTATION_SUFFIX = "__annotation"


@dataclass
class RepairEdit:
    """One ``POST /samples/{id}/edit`` worth of work."""

    sample_id: str
    name: str
    fields: dict = field(default_factory=dict)
    #: True when the sheet row produced no sample at all — a failed import, not a repair.
    missing: bool = False


@dataclass
class RepairResult:
    complete: bool
    total_rows: int
    matched_samples: int
    outstanding: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.complete:
            return (f"repair complete — {self.matched_samples}/{self.total_rows} samples "
                    f"re-read and every field matches the sheet.")
        lines = [
            f"repair INCOMPLETE — {self.matched_samples}/{self.total_rows} sheet rows have a "
            f"sample, {len(self.outstanding)} still differ from the sheet."
        ]
        if self.missing:
            lines.append(f"  no sample at all for: {', '.join(self.missing[:8])}"
                         + (" …" if len(self.missing) > 8 else ""))
        if self.outstanding:
            lines.append(f"  fields still wrong on: {', '.join(self.outstanding[:8])}"
                         + (" …" if len(self.outstanding) > 8 else ""))
        lines.append(
            "  Do NOT submit an execution. Re-run the repair — it is idempotent and will plan "
            "only the remainder. A half-repaired study is indistinguishable from a finished "
            "one except by re-reading it."
        )
        return "\n".join(lines)


def _observed(sample: dict, column: str) -> str:
    """Read a sheet column off a live sample body, resolving the nested annotation key."""
    metadata = sample.get("metadata") or {}
    if column.endswith(_ANNOTATION_SUFFIX):
        parent = metadata.get(column[: -len(_ANNOTATION_SUFFIX)]) or {}
        return str(parent.get("annotation") or "")
    entry = metadata.get(column) or {}
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return str(entry or "")


def _repairable_columns(row: dict) -> list[str]:
    return [c for c in row if c not in _NON_METADATA and not c.startswith("_")]


def _mismatches(row: dict, sample: dict, project_id: str) -> dict:
    wrong: dict = {}
    for column in _repairable_columns(row):
        want = str(row.get(column) or "")
        if _observed(sample, column) != want:
            wrong[column] = want
    if project_id and project_id_of(sample) != project_id:
        wrong["project"] = project_id
    return wrong


def build_repair_plan(
    sheet_rows: list[dict], live_samples: list[dict], *, project_id: str = ""
) -> list[RepairEdit]:
    """Edits needed to make the live samples match the sheet.

    Built from observed state, not from a record of what was written, so a resumed run skips
    what is already correct and plans only the remainder.
    """
    by_name = {s.get("name"): s for s in live_samples}
    plan: list[RepairEdit] = []
    for row in sheet_rows:
        name = row.get("name")
        sample = by_name.get(name)
        if sample is None:
            plan.append(RepairEdit(sample_id="", name=name, missing=True))
            continue
        wrong = _mismatches(row, sample, project_id)
        if wrong:
            plan.append(RepairEdit(sample_id=str(sample.get("id") or ""), name=name, fields=wrong))
    return plan


def summarise_repair(
    sheet_rows: list[dict],
    live_samples: list[dict],
    *,
    project_id: str = "",
    edits_applied: int = 0,
) -> RepairResult:
    """Is the repair finished?

    ``edits_applied`` is accepted and deliberately unused. Counting writes is what made a
    34-sample repair that stopped at 11 look successful; only re-reading every sample settles
    it.
    """
    del edits_applied
    plan = build_repair_plan(sheet_rows, live_samples, project_id=project_id)
    missing = [e.name for e in plan if e.missing]
    outstanding = [e.name for e in plan if not e.missing]
    matched = len(sheet_rows) - len(missing)
    return RepairResult(
        complete=not plan,
        total_rows=len(sheet_rows),
        matched_samples=matched,
        outstanding=outstanding,
        missing=missing,
    )
