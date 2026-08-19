"""How much data can one SRA-direct import job pull before it collapses?

GSE63262 (Drosophila SR proteins) is **132.7 GB across 36 runs**. Submitted as a single
import it died with::

    ERROR ~ Error executing process > 'NFCORE_FETCHNGS:FETCHNGS:SRA_FASTQ_FTP (SRX765636_SRR1659972)'
    Caused by: error exit status (4)

32 fetch processes completed; 36 errored or failed. ``exit status 4`` is wget's *network
failure* code, so everything about the message accuses ENA. ENA was healthy: a byte-range
fetch of that exact file returned ``206`` in 1.1 s and the ENA API returned ``200``, both
minutes after the job died — and half the fetches in the very same job had already succeeded
against the same host. The study was too large to pull in one execution.

Two traps make this expensive to diagnose:

1. **The surfaced reason is not the real one.** Flow reported *"Nextflow 26.04.6 is available
   - Please consider updating your version to it"*. That is the fifth study on which that
   version notice has masked the true cause; taken at face value it sends you to upgrade
   Nextflow.
2. **``exit status 4`` has a precedent that fits.** The previous ``SRA_FASTQ_FTP`` failure
   (E-MTAB-2700) really *was* an EBI outage. The identical signature makes the wrong
   diagnosis feel confirmed, so **reachability must be tested before size is ruled out**.

The measurement that matters is **total bytes per job**, not run count — 36 runs is
unremarkable, 132.7 GB is not.

=====================  ==========  ========
study                  bytes       outcome
=====================  ==========  ========
E-MTAB-2700 (24 smp)   ~0.2 GB     imported
GSE252683 (12 runs)    ~8 GB       imported
GSE63262 (36 runs)     132.7 GB    FAILED
=====================  ==========  ========

The ceiling therefore lies *somewhere between* 8 GB and 132.7 GB and is not otherwise known.
This module refuses to invent a precise limit it cannot support: it passes below the largest
observed success, warns in the unmeasured band while saying plainly that the band is
unmeasured, and refuses at or above the known failure size.

Pure — the caller supplies sizes from ENA's ``filereport``.
"""

from __future__ import annotations

from dataclasses import dataclass

ERROR = "error"
WARNING = "warning"

#: Largest study observed to import successfully in one job (GSE252683).
LARGEST_KNOWN_GOOD_BYTES = 8_000_000_000

#: Size at which an import is known to have failed (GSE63262).
KNOWN_FAILURE_BYTES = 132_700_000_000

#: Default ceiling when splitting. Chosen below the known failure and above the known
#: success; it is a working figure, not a measured limit.
DEFAULT_BATCH_BYTES = 35_000_000_000


@dataclass
class Check:
    severity: str
    message: str


def _sizes_for(accession: str, by_accession: dict) -> list[float] | None:
    """Every mate of every run of one experiment, flattened.

    ENA reports ``fastq_bytes`` as ``R1;R2`` for paired runs. Counting only the first mate
    halves the estimate of a paired study, which is exactly the direction that lets an
    oversized import through.
    """
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


def total_bytes(sheet_rows: list[dict], by_accession: dict) -> float:
    """Total download size for these sheet rows. Unknown accessions contribute nothing.

    Callers must run :func:`check_import_size` first — it is what turns an unknown accession
    into an error rather than a silent zero.
    """
    total = 0.0
    for row in sheet_rows:
        sizes = _sizes_for(str(row.get("accession", "")).strip(), by_accession)
        if sizes:
            total += sum(sizes)
    return total


def check_import_size(sheet_rows: list[dict], by_accession: dict) -> list[Check]:
    """Is this sheet safe to submit as one import job?"""
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

    total = total_bytes(sheet_rows, by_accession)
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
    """Split a sheet into jobs no larger than ``limit``, keeping each target intact.

    Replicates are grouped by ``purification_target`` and never split: if a later batch fails,
    a whole protein is missing and is obvious, rather than one replicate of a pair silently
    landing alone.

    A single group larger than ``limit`` becomes its own batch — dropping it would be worse
    than exceeding the limit, and the caller has already been warned by
    :func:`check_import_size`.
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
