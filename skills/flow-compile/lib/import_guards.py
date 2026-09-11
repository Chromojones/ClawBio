"""What must hold before a sheet is submitted as one import job: size, run expansion,
per-sample-type field rejection and mate selection. Pure.

Story: FAILURES.md#import-guards
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.results import ERROR, Finding as Check, INFO, WARNING

#: Accession prefixes that denote a RUN rather than an experiment.
_RUN_PREFIXES = ("SRR", "ERR", "DRR")




def is_run_accession(accession: str) -> bool:
    return str(accession or "").strip().upper().startswith(_RUN_PREFIXES)


def effective_accession(accession: str, parent_of_run: dict) -> str:
    """What the import fetches when asked for `accession`: a run expands to its parent experiment.
    Unknown accessions are returned unchanged.
    """
    accession = str(accession or "").strip()
    return parent_of_run.get(accession, accession)


def effective_bytes(accession: str, parent_of_run: dict, runs_by_experiment: dict) -> int:
    """Bytes the import will actually pull, i.e. the parent experiment's total."""
    experiment = effective_accession(accession, parent_of_run)
    return int(sum((runs_by_experiment.get(experiment) or {}).values()))


def check_run_expansion(
    accessions: list[str], parent_of_run: dict, runs_by_experiment: dict
) -> list[Check]:
    """Will this sheet fetch something other than what it names?"""
    checks: list[Check] = []
    seen_experiments: dict[str, str] = {}

    for accession in accessions:
        accession = str(accession or "").strip()
        if not accession:
            continue
        experiment = effective_accession(accession, parent_of_run)

        if experiment != accession:
            siblings = runs_by_experiment.get(experiment) or {}
            total = int(sum(siblings.values()))
            own = int(siblings.get(accession, 0))
            if len(siblings) > 1:
                checks.append(Check(
                    ERROR,
                    f"{accession} is a run; the import will fetch its parent {experiment} "
                    f"instead, which holds {len(siblings)} runs totalling "
                    f"{total / 1e9:.1f} GB against the run's own {own / 1e9:.1f} GB. The "
                    f"resulting sample mixes every barcode in the experiment. Name "
                    f"{experiment} in the sheet and accept a pooled sample, or take the "
                    f"reads through a local download to split them per run.",
                ))
            else:
                checks.append(Check(
                    WARNING,
                    f"{accession} is a run and will be fetched as its parent {experiment}. "
                    f"That experiment holds only this run, so nothing extra arrives, but the "
                    f"sheet should name {experiment} so it matches what lands.",
                ))

        if experiment in seen_experiments and seen_experiments[experiment] != accession:
            checks.append(Check(
                ERROR,
                f"{seen_experiments[experiment]} and {accession} both resolve to "
                f"{experiment}, so it would be imported twice and the study duplicated.",
            ))
        seen_experiments.setdefault(experiment, accession)

    return checks

#: Largest import observed to succeed in one job: GSE63262 batch 1 (B52 + Rbp1, both
#: replicates), which landed in ~28 minutes after the whole 132.7 GB study had failed. This
#: replaced an earlier 8 GB figure once the batched retry measured a real upper bound.
LARGEST_KNOWN_GOOD_BYTES = 32_588_391_652

#: Size at which an import is known to have failed: GSE63262's true total across its 36 runs,
#: summed from ENA `fastq_bytes`. This is the measured figure, not a tidied one — the first
#: cut used `132_700_000_000`, which sits 10.9 million bytes ABOVE the real total and so let
#: the very study this module was built from pass with only a warning.
KNOWN_FAILURE_BYTES = 132_689_117_735

#: Default ceiling when splitting. Sits just above the largest measured success and far
#: below the known failure; it is a working figure, not a measured limit.
DEFAULT_BATCH_BYTES = 35_000_000_000




def _sizes_for(accession: str, by_accession: dict) -> list[float] | None:
    """Every mate of every run of one experiment; ENA reports paired sizes as `R1;R2`."""
    runs = by_accession.get(accession)
    if runs is None:
        return None
    sizes: list[float] = []
    for value in runs.values():
        if isinstance(value, (list, tuple)):
            sizes.extend(float(v) for v in value)
        else:
            sizes.append(float(value))
    return sizes


def total_bytes(
    sheet_rows: list[dict],
    by_accession: dict,
    *,
    parent_of_run: dict | None = None,
    runs_by_experiment: dict | None = None,
) -> float:
    """Bytes this sheet will transfer, measuring a run as its whole experiment when the expansion
    maps are given. Unknown accessions contribute nothing.
    """
    total = 0.0
    for row in sheet_rows:
        accession = str(row.get("accession", "")).strip()
        if parent_of_run is not None:
            resolved = effective_accession(accession, parent_of_run)
            if _sizes_for(resolved, by_accession) is not None:
                accession = resolved
        sizes = _sizes_for(accession, by_accession)
        if sizes:
            total += sum(sizes)
    return total


def check_import_size(
    sheet_rows: list[dict],
    by_accession: dict,
    *,
    parent_of_run: dict | None = None,
    runs_by_experiment: dict | None = None,
) -> list[Check]:
    """Is this sheet safe to submit as one import job? Pass the expansion maps when they are known.
    """
    checks: list[Check] = []

    missing = [
        str(row.get("accession", "")).strip()
        for row in sheet_rows
        if _sizes_for(str(row.get("accession", "")).strip(), by_accession) is None
    ]
    if missing:
        checks.append(Check(
            ERROR,
            f"no ENA size for {', '.join(missing)} — the total is an undercount and cannot "
            f"gate the import. Fetch `fastq_bytes` for every accession before submitting.",
        ))

    total = total_bytes(
        sheet_rows, by_accession,
        parent_of_run=parent_of_run, runs_by_experiment=runs_by_experiment,
    )
    gb = total / 1_000_000_000

    if total >= KNOWN_FAILURE_BYTES:
        checks.append(Check(
            ERROR,
            f"{gb:.1f} GB in one import job. A study of {KNOWN_FAILURE_BYTES / 1e9:.1f} GB "
            f"(GSE63262) failed here with SRA_FASTQ_FTP `exit status 4` while ENA was "
            f"provably healthy. Split into batches of about "
            f"{DEFAULT_BATCH_BYTES / 1e9:.0f} GB with `split_into_batches`.",
        ))
    elif total > LARGEST_KNOWN_GOOD_BYTES:
        checks.append(Check(
            WARNING,
            f"{gb:.1f} GB in one import job, above the largest that has succeeded "
            f"({LARGEST_KNOWN_GOOD_BYTES / 1e9:.0f} GB). The true ceiling is not known — it "
            f"lies between that and {KNOWN_FAILURE_BYTES / 1e9:.1f} GB. If this fails in "
            f"SRA_FASTQ_FTP, check ENA reachability first, then batch.",
        ))
    return checks


def split_into_batches(
    sheet_rows: list[dict],
    by_accession: dict,
    *,
    limit: float = DEFAULT_BATCH_BYTES,
) -> list[list[dict]]:
    """Split a sheet into jobs no larger than `limit`, keeping each target's replicates together; a
    single oversized group becomes its own batch.
    """
    groups: dict[str, list[dict]] = {}
    for row in sheet_rows:
        key = str(row.get("purification_target", "")).strip() or str(row.get("name", ""))
        groups.setdefault(key, []).append(row)

    batches: list[list[dict]] = []
    current: list[dict] = []
    current_size = 0.0
    for group in groups.values():
        size = total_bytes(group, by_accession)
        if current and current_size + size > limit:
            batches.append(current)
            current, current_size = [], 0.0
        current.extend(group)
        current_size += size
    if current:
        batches.append(current)
    return batches

#: sample type -> fields the API refuses, despite `batch-template` listing them.
REJECTED_BY_SAMPLE_TYPE: dict[str, frozenset[str]] = {
    "CLIP": frozenset({"strandedness"}),
}




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

_VALID = ("both", "first", "second")


@dataclass
class PairedCheck:
    ok: bool
    reason: str = ""


def check_paired_selection(choice: str, *, layouts: set[str]) -> PairedCheck:
    """Is the `paired` choice coherent with the study's read layouts? An unknown layout is refused.
    """
    choice = str(choice or "").strip().lower()
    if choice not in _VALID:
        return PairedCheck(False, f"{choice!r} is not one of {_VALID}; anything else is silently ignored")

    normalised = {str(x).strip().upper() for x in layouts if str(x).strip()}
    if not normalised:
        return PairedCheck(False, "read layout is unknown — read ENA's `library_layout` before choosing a mate")
    if normalised == {"SINGLE"}:
        if choice == "both":
            return PairedCheck(True)
        return PairedCheck(
            False,
            f"paired={choice!r} on SINGLE-end data: there is no mate to select, and the "
            f"samplesheet ends up with both read columns blank. Use 'both'.",
        )
    if normalised == {"PAIRED"}:
        return PairedCheck(True)
    return PairedCheck(
        False,
        f"mixed read layouts {sorted(normalised)} in one submission — split the study by "
        f"layout, or the single-end rows will lose their reads",
    )
