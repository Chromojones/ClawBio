"""Read imported samples back and compare them to the sheet that produced them.

**A ``COMPLETED`` import job is not evidence that the metadata arrived.**

GSE252683 imported 12/12 samples with every read attached and no error anywhere. Six of the
sheet's columns had nevertheless been discarded: ``flowbio samples import`` accepts
``purification_target__annotation`` and ``source__annotation``, reports success, and stores
neither. All twelve samples silently lost ``nFLAG``, ``Flp-In T-REx`` and ``neuroblastoma``.

This is the same shape as the missing ``project`` column (fact 2 in
``reference/sra-direct-import.md``): the import sheet is not a validated schema, so an
unrecognised column is dropped rather than rejected. The only reliable defence is to read
the samples back — which also catches the next dropped column, whatever it turns out to be.

Repair is ``POST /samples/{id}/edit`` with the missing columns; see
``lib/vendor/flow_api/metadata/flow_edit_samples.py``.

Two decoys are handled deliberately, because both produced a confident wrong answer on live
data before they were understood:

``GET /projects/{id}/samples``
    returns **trimmed** samples with no ``metadata`` block at all. Verifying against that
    listing reports every field of every sample as dropped — 60 phantom discrepancies on a
    study whose only real fault was two annotation columns. Such a sample raises rather than
    reporting, because it is a bug in the caller, not in the data.

``filesets[].data``
    is where reads live. There is no top-level ``data`` key, so ``len(sample["data"])``
    reports 0 files for a fully populated sample and invents a catastrophe.

This module is pure; the caller supplies the sheet rows and the sample bodies.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Sheet columns that are not sample metadata and so are never compared field-by-field.
_NON_METADATA_COLUMNS = frozenset({"accession", "sample_type", "name", "organism"})

_ANNOTATION_SUFFIX = "__annotation"


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
    if column.endswith(_ANNOTATION_SUFFIX):
        return str(_metadata_block(sample, column[: -len(_ANNOTATION_SUFFIX)]).get("annotation") or "")
    return str(_metadata_block(sample, column).get("value") or "")


def count_reads(sample: dict) -> int:
    """Number of data files attached, counted where Flow actually keeps them."""
    return sum(len(fileset.get("data") or []) for fileset in (sample.get("filesets") or []))


def project_id_of(sample: dict) -> str:
    """The owning project id, whether the API nests it or returns it bare."""
    project = sample.get("project")
    if isinstance(project, dict):
        project = project.get("id")
    return "" if project is None else str(project)


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
            if not want or column in _NON_METADATA_COLUMNS:
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
