"""Audit a Flow execution for samples that were silently dropped.

**An execution's overall status is not evidence that a study was analysed.**

GSE78030 execution ``261164407803419211`` launched seven ~10 GB ``CAT_FASTQ`` merges at
once. Two were SIGKILLed (exit 137) and the Nextflow log recorded::

    NOTE: Process CAT_FASTQ (YTHDF1...) terminated with an error exit status (137)
          -- Error is ignored

``errorStrategy = ignore`` means the pipeline continues. YTHDF1 and YTHDC1 produced no
downstream stages at all, so the run was heading for a green finish having analysed **5 of 7
samples** — and nothing in the execution summary would have said so.

Two shapes matter, and the second is the dangerous one:

1. a stage is ``FAILED`` — visible if you go looking;
2. a sample simply **stops**, with no failed row anywhere.

**Each sample is compared against the run's own deepest sample**, not against a named
terminal stage. A first version hardcoded ``MULTIQC`` and flagged every finished run, because
MULTIQC is a run-level aggregate with no sample attached, so no sample ever "reaches" it.
Peer comparison needs no pipeline knowledge and cannot repeat that mistake — and a guardrail
that fires on correct data is worse than none, because it gets switched off.

This module is pure; the caller supplies ``process_executions`` from the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FAILED_STATUSES = {"FAILED", "ERROR", "ABORTED"}

#: Exit codes worth naming, because they point at the environment rather than the data and
#: so change what you do about them.
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
    """Samples that failed a stage, or completed fewer stages than the deepest sample.

    ``finished=False`` reports only hard failures — a sample still working through the
    pipeline has legitimately not caught up yet, and calling that "dropped" would make the
    check useless mid-run. A failed stage is actionable immediately either way.

    Processes with no sample attached (MULTIQC, reference preparation) are ignored entirely.
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
