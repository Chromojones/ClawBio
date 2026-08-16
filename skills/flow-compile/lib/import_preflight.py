"""Ask the project what it already holds, immediately before importing.

**A status document is not evidence about live state — including one you wrote yourself.**

E-MTAB-2700's ``ANALYSIS_STATUS.md`` said *BLOCKED — everything ready, EBI file server down*,
and stated that both import jobs had reported ``sample_ids: []``, so "a retry cannot
duplicate". That was accurate when written. Two days later the original imports had actually
completed — ``watch_import.log`` recorded ``cell: COMPLETED, 12 samples`` and
``virion: COMPLETED, 12 samples`` — and the note was never updated.

Re-running the import on the strength of the note produced **48 samples in a 24-sample
project**, every one duplicated, which then had to be untangled by creation timestamp and
deleted. The project itself was one request away and could not have been stale.

Run this before every import::

    GET https://app.flow.bio/api/projects/{id}/samples?page=1&count=100   # count=200 → HTTP 400

The **trimmed** listing is the correct endpoint here: a pre-flight needs only names, and the
import preserves the sheet's ``name`` verbatim. (That same trimmed shape is useless for
``import_verify``, which needs metadata — see that module's note.)

This module is pure; the caller supplies the listing payload.
"""

from __future__ import annotations


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
