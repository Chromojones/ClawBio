"""The import round trip: what is already there, what arrived, what to fix.

Preflight, verify and repair are three phases of one question, and they carried two copies of
the same constant under two names — ``import_verify._NON_METADATA_COLUMNS`` and
``import_repair._NON_METADATA``, both ``{accession, sample_type, name, organism}``.

Both were right for flowbio 0.10.0 and both went stale when ``project`` became a reserved
import-sheet column in 0.12.0: a reserved column then reads as a metadata column, so
``live_metadata()`` looks for ``metadata["project"]``, finds nothing (the API returns it at the
top level), and every sample is reported as ``project dropped by the import`` while the repair
plan queues an edit re-setting a project that is already correct.

The set now has one definition, taken from ``sra_import.RESERVED_SHEET_COLUMNS``, which is
itself asserted equal to flowbio's own ``RESERVED_COLUMNS``.

Pure. Story: FAILURES.md#import-check
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.flow_client import project_id_of

#: Mirrors `flowbio.cli._accession_sheet.RESERVED_COLUMNS`, asserted equal to it by test so a
#: downgrade fails loudly. Defined here rather than in `sra_import` because the checkers are
#: pure and must not pull pandas in for six strings; `sra_import` imports it from here.
RESERVED_SHEET_COLUMNS: tuple[str, ...] = (
    "accession", "name", "organism", "project", "pubmed", "sample_type",
)

#: Sheet columns the API does NOT deliver inside `metadata`. One definition, tracking flowbio.
NON_METADATA_COLUMNS = frozenset(RESERVED_SHEET_COLUMNS)

#: Flow stores an attribute's free-text companion in a nested `annotation` field; the sheet
#: carries it as a suffixed column.
ANNOTATION_SUFFIX = "__annotation"




#: Sheet columns that are not sample metadata and so are never compared field-by-field.



@dataclass(frozen=True)
class Discrepancy:
    """One thing the sheet asked for that the imported sample does not have."""

    sample: str
    field: str
    expected: str
    actual: str
    detail: str = ""


def _metadata_block(sample: dict, field: str) -> dict:
    return (sample.get("metadata") or {}).get(field) or {}


def live_metadata(sample: dict, column: str) -> str:
    """Read a sheet column off a live sample, resolving ``__annotation`` to the nested key.

    ``source__annotation`` is not a field of its own: it is the ``annotation`` key of the
    ``source`` block. Reading flat keys is what made an earlier verifier pass on samples
    whose metadata had never been written.
    """
    if column.endswith(ANNOTATION_SUFFIX):
        return str(_metadata_block(sample, column[: -len(ANNOTATION_SUFFIX)]).get("annotation") or "")
    return str(_metadata_block(sample, column).get("value") or "")


def count_reads(sample: dict) -> int:
    """Number of data files attached, counted where Flow actually keeps them."""
    return sum(len(fileset.get("data") or []) for fileset in (sample.get("filesets") or []))




def find_import_discrepancies(
    sheet_rows: list[dict],
    live_samples: list[dict],
    *,
    project_id: str = "",
    expect_pubmed: str = "",
    expect_reads: bool = True,
) -> list[Discrepancy]:
    """Compare each sheet row against the sample it produced.

    Samples are paired to rows by ``name``, which the import preserves verbatim. Rows with
    no sample and samples with no row are both reported: an unpaired sample is usually
    debris from an earlier attempt, and deleting the wrong one is expensive.

    A sample carrying no ``metadata`` block at all raises ``ValueError`` — that is the
    trimmed listing shape, and reporting it as a wall of missing fields would bury the one
    real finding.
    """
    for sample in live_samples:
        # The trimmed listing carries `metadata` as an EMPTY DICT, so the key's presence
        # proves nothing — only a populated block does. A guard testing `"metadata" not in
        # sample` looks right, passes a fabricated fixture, and lets the real listing through.
        if not sample.get("metadata"):
            raise ValueError(
                f"sample {sample.get('name') or sample.get('id')!r} has an empty `metadata` block — "
                "this is the trimmed shape from GET /projects/{id}/samples. Fetch each sample "
                "with GET /samples/{id} instead; verifying against the listing reports every "
                "field as missing."
            )

    by_name = {sample.get("name", ""): sample for sample in live_samples}
    found: list[Discrepancy] = []

    for row in sheet_rows:
        name = (row.get("name") or "").strip()
        sample = by_name.pop(name, None)
        if sample is None:
            found.append(Discrepancy(
                sample=name, field="sample", expected=name, actual="",
                detail="in the sheet but not imported",
            ))
            continue

        for column, want in row.items():
            want = (want or "").strip()
            if not want or column in NON_METADATA_COLUMNS:
                continue
            got = live_metadata(sample, column)
            if got != want:
                found.append(Discrepancy(
                    sample=name, field=column, expected=want, actual=got,
                    detail="dropped by the import" if not got else "differs from the sheet",
                ))

        if project_id and project_id_of(sample) != str(project_id):
            found.append(Discrepancy(
                sample=name, field="project", expected=str(project_id),
                actual=project_id_of(sample) or "(none)",
                detail="the import sheet has no project column — assign after import",
            ))

        if expect_pubmed and str(sample.get("pubmed") or "") != str(expect_pubmed):
            found.append(Discrepancy(
                sample=name, field="pubmed", expected=str(expect_pubmed),
                actual=str(sample.get("pubmed") or ""),
                detail="`pubmed` is a top-level sample property, not metadata",
            ))

        if expect_reads and count_reads(sample) == 0:
            found.append(Discrepancy(
                sample=name, field="reads", expected="at least 1 file", actual="0 files",
                detail="no data attached — the fetch failed for this accession",
            ))

    for name, sample in by_name.items():
        found.append(Discrepancy(
            sample=name, field="sample", expected="", actual=name,
            detail=f"sample {sample.get('id')} is not in the sheet — debris from an earlier attempt?",
        ))

    return found


def format_report(discrepancies: list[Discrepancy], *, total_rows: int) -> str:
    """Human-readable summary, grouped by field so a systematic drop reads as one fault."""
    if not discrepancies:
        return f"Import verified: {total_rows} row(s), 0 discrepancies."

    by_field: dict[str, list[Discrepancy]] = {}
    for item in discrepancies:
        by_field.setdefault(item.field, []).append(item)

    lines = [
        f"Import verification: {len(discrepancies)} discrepanc"
        f"{'y' if len(discrepancies) == 1 else 'ies'} across {total_rows} row(s).",
        "",
    ]
    for field, items in by_field.items():
        scope = "all rows" if len(items) == total_rows else f"{len(items)} row(s)"
        lines.append(f"{field} — {scope}: {items[0].detail}")
        for item in items:
            lines.append(f"    {item.sample}: expected {item.expected!r}, got {item.actual!r}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"




#: Sheet columns that are not sample metadata and are never repaired.

#: Suffix marking a column that lives as the ``annotation`` of its parent attribute rather
#: than as a metadata key of its own — the pair the import silently discards.


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
    if column.endswith(ANNOTATION_SUFFIX):
        parent = metadata.get(column[: -len(ANNOTATION_SUFFIX)]) or {}
        return str(parent.get("annotation") or "")
    entry = metadata.get(column) or {}
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return str(entry or "")


def _repairable_columns(row: dict) -> list[str]:
    return [c for c in row if c not in NON_METADATA_COLUMNS and not c.startswith("_")]


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




def names_from_listing(payload: dict | None) -> set[str]:
    """Sample names from a project listing response.

    Raises when the payload is not a listing. "I saw nothing" and "I could not look" are
    opposite conclusions here, and conflating them is how a failed lookup became a silent
    no-op upload that reported success. A listing response has a ``samples`` key; a project
    response has ``id`` and ``name``, so passing the wrong one is a real and easy mistake.
    """
    if not isinstance(payload, dict) or "samples" not in payload:
        raise ValueError(
            "payload has no `samples` key — this is not a project listing response. "
            "Use GET /projects/{id}/samples?count=100, and do not treat a failed lookup "
            "as an empty project."
        )
    samples = payload.get("samples") or []
    return {str(s.get("name", "")).strip() for s in samples if s.get("name")}


def find_already_present(sheet_rows: list[dict], existing_names: set[str]) -> list[str]:
    """Sheet names that the project already holds, in sheet order.

    A non-empty result means the import would duplicate. Whether that is wrong depends on
    intent — resuming a partial import is legitimate — so this reports rather than refuses,
    and the caller decides.
    """
    return [
        name
        for row in sheet_rows
        if (name := str(row.get("name", "")).strip()) and name in existing_names
    ]
