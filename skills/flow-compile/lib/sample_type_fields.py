"""Fields the batch template demands that the API refuses for that sample type.

``flowbio samples batch-template --sample-type CLIP`` prints::

    Required columns: name, reads1, five_prime_barcode_sequence, purification_target, strandedness

Supplying exactly that set to ``samples upload`` returns::

    Error: {'strandedness': ['Not a valid attribute for this sample type.']}

``strandedness`` is RNA-Seq only. The template says CLIP requires it, the API rejects it, and
the same client ships both. Ten E-MTAB-13331 uploads failed on it in one batch, and the
contradiction was already written down in this skill's design notes from the PARP13 run
months earlier — which is the point. Knowing it is not enough, because the template is what
you naturally reach for when building a sheet.

The rejection is at least loud. What makes it worth a guard is the cost shape: ``samples
upload`` sends one sample per call, so the error arrives *after* the reads have transferred,
and repeats for every sample in the batch.

Pure. Only sample types actually observed to refuse a field appear here; nothing is inferred.
"""

from __future__ import annotations

from dataclasses import dataclass

ERROR = "error"

#: sample type -> fields the API refuses, despite `batch-template` listing them.
REJECTED_BY_SAMPLE_TYPE: dict[str, frozenset[str]] = {
    "CLIP": frozenset({"strandedness"}),
}


@dataclass
class Check:
    severity: str
    message: str


def _rejected(sample_type: str) -> frozenset[str]:
    return REJECTED_BY_SAMPLE_TYPE.get(str(sample_type or "").strip().upper(), frozenset())


def check_upload_fields(row: dict, *, sample_type: str) -> list[Check]:
    """Does this row name a field the API will refuse for this sample type?"""
    checks: list[Check] = []
    for field in sorted(_rejected(sample_type)):
        if field in row:
            checks.append(Check(
                ERROR,
                f"{field!r} is listed as REQUIRED by `batch-template --sample-type "
                f"{sample_type}`, but the API refuses it: \"Not a valid attribute for this "
                f"sample type\". It belongs to RNA-Seq only. Drop it from the sheet. The "
                f"template is wrong, not the sheet, and `samples upload` sends one sample per "
                f"call so this rejects only after the reads have been transferred.",
            ))
    return checks


def strip_rejected(row: dict, *, sample_type: str) -> dict:
    """A copy of ``row`` without the fields this sample type refuses."""
    rejected = _rejected(sample_type)
    return {k: v for k, v in row.items() if k not in rejected}
