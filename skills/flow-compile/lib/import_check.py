"""The import round trip: what the project holds, what arrived, and what to fix. Pure.

Story: FAILURES.md#import-check
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
    """A sheet column read off a live sample; an `__annotation` column resolves to the nested
    `annotation` key of its parent field.
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
    """Compare each sheet row against the sample it produced, paired by name.

    Rows with no sample and samples with no row are both reported. A sample with empty `metadata`
    (the trimmed listing shape) raises, and an envelope shorter than its `count` is refused.
    """
    if isinstance(live_samples, dict):
        _refuse_if_truncated(live_samples, live_samples.get("samples") or [], "verification")
        live_samples = live_samples.get("samples") or []

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
                detail="the sample is not in the run's project",
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
    """Edits that make the live samples match the sheet, built from observed state so a resumed run
    plans only what is still wrong.
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


def names_from_listing(payload: dict | None) -> set[str]:
    """Sample names from a project listing. Raises on a payload that is not a listing, or that holds
    fewer samples than it promises: a failed or partial lookup must not read as an empty project.
    """
    if not isinstance(payload, dict) or "samples" not in payload:
        raise ValueError(
            "payload has no `samples` key — this is not a project listing response. "
            "Use GET /projects/{id}/samples?count=100, and do not treat a failed lookup "
            "as an empty project."
        )
    samples = payload.get("samples") or []
    _refuse_if_truncated(payload, samples, "pre-flight")
    return {str(s.get("name", "")).strip() for s in samples if s.get("name")}


def _refuse_if_truncated(payload: dict, items: list, what: str) -> None:
    """Raise when a listing holds fewer samples than its `count`: one page is not the project.
    """
    total = payload.get("count")
    if isinstance(total, int) and len(items) < total:
        raise ValueError(
            f"listing holds {len(items)} of {total} samples — it is one page, not the "
            f"project. A truncated listing makes this {what} meaningless; collect every "
            f"page (flow_client.FlowClient.project_samples) and retry."
        )


def find_already_present(sheet_rows: list[dict], existing_names: set[str]) -> list[str]:
    """Sheet names the project already holds, in sheet order. Reports rather than refuses, since
    resuming a partial import is legitimate.
    """
    return [
        name
        for row in sheet_rows
        if (name := str(row.get("name", "")).strip()) and name in existing_names
    ]
