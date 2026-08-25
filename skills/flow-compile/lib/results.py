"""One finding type and one verdict type, replacing seventeen.

Every guardrail here returns a result, and each got its own class as it was written: four
byte-identical ``Check`` dataclasses, five copies of ``ERROR``/``WARNING``, three
``format_report()`` functions, seventeen result classes. They are two shapes:

* :class:`Finding` — something wrong with one row or sample, returned as a list.
* :class:`Verdict` — one question answered, returned singly, carrying its evidence.

``Finding`` must stay drop-in for ``metadata_validate.Check``, a ``NamedTuple`` documented as
"Indexable as (severity, message) by design" and relied on positionally
(``issues[0][0] == ERROR``) in 20+ assertions. Hence ``__getitem__``, not just ``__iter__``.

Story: FAILURES.md#result-type-sprawl
"""

from __future__ import annotations

from dataclasses import dataclass, field as _field

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: Positional order, frozen by `metadata_validate.Check`'s NamedTuple layout.
_POSITIONAL = ("severity", "message", "field")


@dataclass
class Finding:
    """Something wrong with one row, sample or accession.

    Absorbs every ``Check``, ``MetadataIssue``, ``AnnotationWarning``, ``Discrepancy`` and
    ``DroppedSample``. The extra fields are optional so the common two-argument construction
    reads exactly as it did before.
    """

    severity: str
    message: str
    field: str = ""
    row: int = -1
    subject: str = ""
    expected: str = ""
    actual: str = ""

    def __getitem__(self, index: int) -> str:
        # NamedTuple compatibility: `issues[0][0] == ERROR` is load-bearing in
        # tests/test_metadata_validate.py. Attribute access alone would break it in a way
        # that reads as a logic regression rather than a container change.
        try:
            return getattr(self, _POSITIONAL[index])
        except IndexError:
            raise IndexError(f"Finding index out of range: {index}") from None

    def __iter__(self):
        for name in _POSITIONAL[:2]:
            yield getattr(self, name)

    def describe(self) -> str:
        where = " ".join(p for p in (self.subject, self.field) if p)
        detail = ""
        if self.expected or self.actual:
            detail = f" (expected {self.expected!r}, got {self.actual!r})"
        return f"[{self.severity}] {where + ': ' if where else ''}{self.message}{detail}"


@dataclass
class Verdict:
    """One question answered, with the evidence that settled it.

    ``evidence`` carries what the specific check measured — ``compared`` for a reference
    cross-check, ``separator_count`` for UMI safety, ``release_date`` for availability — so a
    caller can distinguish *how* a verdict was reached, not merely whether it passed.
    """

    ok: bool
    reason: str = ""
    evidence: dict = _field(default_factory=dict)
    notes: list[str] = _field(default_factory=list)

    def describe(self) -> str:
        head = "OK" if self.ok else "REFUSED"
        parts = [f"{head}{': ' + self.reason if self.reason else ''}"]
        if self.evidence:
            parts.append("  " + ", ".join(f"{k}={v}" for k, v in sorted(self.evidence.items())))
        parts.extend(f"  {n}" for n in self.notes)
        return "\n".join(parts)


def blocking(findings: list[Finding]) -> list[Finding]:
    """Only errors stop a run; warnings are for the reader."""
    return [f for f in findings if f.severity == ERROR]


def findings_to_json(findings: list[Finding]) -> list[dict]:
    return [
        {k: getattr(f, k) for k in
         ("severity", "message", "field", "row", "subject", "expected", "actual")}
        for f in findings
    ]


def render_findings(findings: list[Finding], *, title: str, total: int, note: str = "") -> str:
    """A report that leads with how much was checked, not just what failed.

    Every ``format_report()`` copy opened with "N of M", because a bare failure list cannot
    distinguish "1 bad sample of 24" from "1 bad sample of 1".
    """
    lines = [f"# {title}", ""]
    if not findings:
        lines.append(f"{total} checked, no findings.")
    else:
        errors = len(blocking(findings))
        lines.append(f"{len(findings)} finding(s) across {total} checked ({errors} blocking).")
        lines.append("")
        for f in findings:
            lines.append(f"- {f.describe()}")
    if note:
        lines += ["", note]
    return "\n".join(lines) + "\n"
