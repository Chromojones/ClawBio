"""Two independent sources must agree about the reference — and must actually be compared.

Before a CLIP execution is submitted, 21 reference files are resolved by filename from the
genome prep execution, then cross-checked against a *completed* run of the same organism. Two
sources, so a silently wrong reference cannot reach the pipeline.

The obvious implementation has a hole::

    shared = set(prep) & set(reference_run)
    if any(prep[k] != reference_run[k] for k in shared): refuse

If the two share no keys, ``shared`` is empty, nothing is compared, no disagreement is found,
and the submitter proceeds after printing ``0 cross-checked``. **Zero disagreements is not
agreement** — the same shape as a database search that runs no queries and reports the study
absent.

Two live routes into it:

- **The reference run is a different organism.** GSE63262 is the first *Drosophila* study, so
  no completed fly CLIP run exists; the constant still pointed at a mouse execution inherited
  from the previous study's submitter. Mouse and fly share key names, so that case refuses
  loudly — but only by luck of the naming.
- **The reference run's ``data_params`` is shaped differently** — empty, or keyed by file id
  instead of by role. Then the intersection genuinely is empty and the check evaporates.

So three outcomes are distinguished, never two: **agreed**, **disagreed**, and **not
compared**. The first study of any new organism legitimately has nothing to compare against;
that is normal, and it has to be declared in words and recorded in the output rather than
falling out of an empty set intersection.

Pure — the caller fetches both executions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CrossCheck:
    ok: bool
    compared: int
    disagreements: list[str] = field(default_factory=list)
    reason: str = ""

    def describe(self) -> str:
        if self.disagreements:
            return ("reference MISMATCH between the prep execution and the completed run:\n  "
                    + "\n  ".join(self.disagreements)
                    + "\nDo not submit — one of the two sources points at the wrong genome.")
        if self.ok and self.compared:
            return f"reference agreed on {self.compared} file(s) across two sources."
        if self.ok:
            return (f"reference taken from a SINGLE source — no completed run was compared "
                    f"against. Declared reason: {self.reason}. The 21 filenames were resolved "
                    f"from the prep execution alone, so assembly and annotation release are "
                    f"unverified by a second source; check them by eye before submitting.")
        return ("reference NOT COMPARED — 0 file(s) overlapped between the prep execution and "
                "the supplied reference run, so no disagreement could be found. That is not "
                "agreement. Either supply a completed run of the SAME organism, or declare "
                "`no_reference_run_reason` to proceed on a single source deliberately.")


def cross_check_reference(
    prep_params: dict,
    reference_params: dict | None,
    *,
    no_reference_run_reason: str = "",
) -> CrossCheck:
    """Compare two independently-resolved reference mappings.

    ``reference_params`` of ``None`` means no completed run was supplied at all — legitimate
    for the first study of an organism, but only with a stated reason.
    """
    if reference_params is None:
        if no_reference_run_reason.strip():
            return CrossCheck(ok=True, compared=0, reason=no_reference_run_reason.strip())
        return CrossCheck(ok=False, compared=0)

    shared = sorted(set(prep_params) & set(reference_params))
    disagreements = [
        f"{key}: prep={prep_params[key]} vs completed-run={reference_params[key]}"
        for key in shared
        if str(prep_params[key]) != str(reference_params[key])
    ]
    if disagreements:
        return CrossCheck(ok=False, compared=len(shared), disagreements=disagreements)
    if not shared:
        # Nothing overlapped. A reason cannot rescue this: a reference run WAS supplied and
        # could not be compared, which means one of the two is not what it is believed to be.
        return CrossCheck(ok=False, compared=0)
    return CrossCheck(ok=True, compared=len(shared))
