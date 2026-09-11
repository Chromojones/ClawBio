"""Audit a Flow execution for samples that were silently dropped.

An execution's status is not evidence every sample was analysed: with `errorStrategy = ignore`
a sample can fail a process, or simply stop, and the run still finishes. Each sample is
compared against the run's deepest sample, so no pipeline stage names are needed. Pure; the
caller supplies `process_executions` from `GET /executions/{id}`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FAILED_STATUSES = {"FAILED", "ERROR", "ABORTED"}

_SIGNAL_EXITS = {
    "137": "SIGKILL (128+9) — out of memory or a scheduler kill, not bad data",
    "143": "SIGTERM (128+15) — cancelled or timed out",
}
_EXIT_RE = re.compile(r"exit status \((\d+)\)")


@dataclass
class DroppedSample:
    """A sample that failed a stage, or fell short of its peers."""

    sample_name: str
    reason: str
    stages_completed: int = 0
    stages_expected: int = 0


def _stage_of(process: dict) -> str:
    return str(process.get("process_name", "")).split(":")[-1].strip()


def _sample_of(process: dict) -> str:
    sample = process.get("sample") or {}
    return str(sample.get("name") or "").strip()


def find_dropped_samples(
    process_executions: list[dict],
    *,
    finished: bool = True,
    log: str = "",
) -> list[DroppedSample]:
    """Samples that failed a process, or completed fewer processes than the deepest sample.

    `finished=False` reports hard failures only, since mid-run a sample may not have caught up.
    Processes with no sample attached (MULTIQC, reference preparation) are ignored.
    """
    completed: dict[str, set[str]] = {}
    failed: dict[str, set[str]] = {}
    for process in process_executions:
        sample = _sample_of(process)
        if not sample:
            continue  # run-level aggregate — belongs to no sample
        status = str(process.get("status") or "").upper()
        stage = _stage_of(process)
        if status == "COMPLETED":
            completed.setdefault(sample, set()).add(stage)
        elif status in _FAILED_STATUSES:
            failed.setdefault(sample, set()).add(stage)
    samples = sorted(set(completed) | set(failed))
    if not samples:
        return []

    exit_note = ""
    match = _EXIT_RE.search(log or "")
    if match:
        code = match.group(1)
        exit_note = f" [exit {code}: {_SIGNAL_EXITS.get(code, 'non-zero exit')}]"

    # The deepest sample defines what "complete" means for this run.
    expected = max((len(completed.get(s, ())) for s in samples), default=0)

    dropped: list[DroppedSample] = []
    for sample in samples:
        done = len(completed.get(sample, ()))
        if sample in failed:
            stages = ", ".join(sorted(failed[sample]))
            dropped.append(
                DroppedSample(
                    sample_name=sample,
                    reason=(
                        f"{stages} failed — the pipeline may ignore this and carry on "
                        f"without the sample{exit_note}"
                    ),
                    stages_completed=done,
                    stages_expected=expected,
                )
            )
            continue
        if not finished or done >= expected:
            continue
        dropped.append(
            DroppedSample(
                sample_name=sample,
                reason=(
                    f"completed {done} of {expected} stages with no failed stage recorded — "
                    "silently dropped part-way through"
                ),
                stages_completed=done,
                stages_expected=expected,
            )
        )
    return dropped


def format_report(dropped: list[DroppedSample], *, total_samples: int) -> str:
    """One-line-per-sample summary for a human."""
    if not dropped:
        return f"All {total_samples} samples completed."
    lines = [f"{len(dropped)} of {total_samples} samples did NOT complete:"]
    lines += [f"  - {d.sample_name}: {d.reason}" for d in dropped]
    return "\n".join(lines)
