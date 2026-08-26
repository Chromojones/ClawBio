"""``<output>/state.json`` — what each stage read, wrote, and decided.

The old orchestrator made the user run one command three times, because a single command owned
both ``annotation.csv`` and the FASTQ filenames and the filenames only settle once the reads are
on disk. Re-execution *was* the dependency mechanism.

Here the dependency is explicit. A stage declares its inputs; ``begin()`` hashes their contents
plus the stage's own CLI args and says whether the work still stands. Re-running a finished stage
costs nothing; changing an upstream artefact changes the digest and the stage recomputes.

The file carries decisions, never data — anything recoverable from a real artefact is read from
that artefact — so the recovery for a damaged ``state.json`` is always to delete it, and that is
what the error says.

Story: FAILURES.md#state-contract
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

#: Bump only for a change old state cannot be read through; `load` refuses anything else.
SCHEMA = 1

STATE_FILE = "state.json"

#: Stage outcomes. GATED means a human artefact is required, not that anything failed.
OK = "ok"
GATED = "gated"
FAILED = "failed"

_TERMINAL_OK = frozenset({OK})


class StateError(RuntimeError):
    """`state.json` is unreadable. Always recoverable by deleting it."""


class PrerequisiteError(RuntimeError):
    """A stage was asked to run before the stage it depends on completed."""


def _path(output_dir) -> Path:
    return Path(output_dir) / STATE_FILE


def load(output_dir) -> dict:
    """The whole state document; an empty one when the run is fresh."""
    path = _path(output_dir)
    if not path.exists():
        return {"schema": SCHEMA, "study": {}, "route": {}, "stages": {}}
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StateError(
            f"{path} is not readable JSON ({exc}). It holds decisions, not data: "
            f"delete it and re-run the stages you need."
        ) from None
    schema = doc.get("schema")
    if schema != SCHEMA:
        raise StateError(
            f"{path} has schema {schema}, this skill writes schema {SCHEMA}. "
            f"Delete it and re-run."
        )
    doc.setdefault("stages", {})
    doc.setdefault("study", {})
    doc.setdefault("route", {})
    return doc


def save(output_dir, doc: dict) -> None:
    """Write the document atomically, so an interrupted run cannot truncate it."""
    path = _path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(doc, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def digest(inputs: Iterable = (), args: Sequence[str] = ()) -> str:
    """Content hash of the declared inputs plus the stage's own arguments.

    Args are part of it because the same inputs run with ``--paired second`` are a different
    computation from the same inputs run with ``--paired both``.
    """
    sha = hashlib.sha256()
    for item in sorted(str(i) for i in inputs):
        path = Path(item)
        sha.update(path.name.encode())
        sha.update(path.read_bytes() if path.is_file() else b"\0missing")
    for arg in args:
        sha.update(b"\0")
        sha.update(str(arg).encode())
    return sha.hexdigest()


def status(output_dir, stage: str) -> str:
    """How ``stage`` finished, or ``""`` if it has not run."""
    return load(output_dir)["stages"].get(stage, {}).get("status", "")


def record(output_dir, stage: str, outcome: str, *, outputs: Sequence[str] = (),
           inputs: Iterable = (), args: Sequence[str] = (), findings=None,
           release: str = "", note: str = "", **extra) -> None:
    """Record how a stage finished. ``outputs`` are paths relative to the output dir."""
    doc = load(output_dir)
    entry = {
        "status": outcome,
        "inputs_digest": digest(inputs, args),
        "outputs": [str(o) for o in outputs],
    }
    if findings is not None:
        entry["findings"] = findings
    if release:
        entry["release"] = release
    if note:
        entry["note"] = note
    entry.update(extra)
    doc["stages"][stage] = entry
    save(output_dir, doc)


def begin(output_dir, stage: str, *, inputs: Iterable = (), args: Sequence[str] = (),
          force: bool = False) -> bool:
    """Should this stage do its work? ``False`` means the previous run still stands.

    A digest match alone is not enough: every output the stage recorded must still exist. A
    completed stage whose artefacts were deleted has not, in any sense the next stage cares
    about, completed.
    """
    if force:
        return True
    entry = load(output_dir)["stages"].get(stage)
    if not entry or entry.get("status") not in _TERMINAL_OK:
        return True
    if entry.get("inputs_digest") != digest(inputs, args):
        return True
    root = Path(output_dir)
    return not all((root / out).exists() for out in entry.get("outputs", []))


def require(output_dir, *stages: str) -> None:
    """Refuse to proceed unless every named stage completed."""
    doc = load(output_dir)
    for stage in stages:
        entry = doc["stages"].get(stage)
        state = (entry or {}).get("status", "")
        if state in _TERMINAL_OK:
            continue
        if state == GATED:
            release = (entry or {}).get("release", "")
            raise PrerequisiteError(
                f"{stage} is waiting on approval"
                + (f"; re-run it with {release} once the evidence is confirmed" if release else "")
            )
        raise PrerequisiteError(
            f"{stage} has not completed ({state or 'never run'}); run it first"
        )


def set_route(output_dir, **fields) -> None:
    """Record the routing decision taken at stage 06."""
    doc = load(output_dir)
    doc["route"].update({k: v for k, v in fields.items()})
    save(output_dir, doc)


def route(output_dir) -> dict:
    """The routing decision. Refuses rather than guessing a line."""
    decided = load(output_dir)["route"]
    if not decided.get("line"):
        raise PrerequisiteError("no route recorded; run 06_route.py first")
    return decided


def set_study(output_dir, **fields) -> None:
    """Record study-level identity (accession, project id, sample count)."""
    doc = load(output_dir)
    doc["study"].update(fields)
    save(output_dir, doc)


def study(output_dir) -> dict:
    return load(output_dir)["study"]
