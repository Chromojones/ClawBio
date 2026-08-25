"""What will the import actually fetch, as opposed to what the sheet asked for?

``flowbio samples import`` accepts a run accession and silently substitutes its **parent
experiment**. Measured on GSE78030::

    requested  SRR3175580     2,213,904,326 bytes   1 run
    delivered  SRX1590001    10,075,864,988 bytes   4 runs
    job status COMPLETED

Neither ENA nor fetchngs is responsible: ``filereport?accession=SRR3175580&result=read_run``
returns exactly one row, and that is the same endpoint fetchngs resolves against. The
substitution is in Flow's wrapper, and it is not reported.

Resolving the run yourself does **not** win back per-run access; the wrapper substitutes
regardless. What it buys is knowing before the download, which is the part that cost time:

**Per-run samples are unreachable through import.** GSE78030's 7 experiments hold 26 runs
(4+4+4+4+4+3+3), one biological replicate each with its own barcode. Importing 26 run
accessions would produce 26 samples that each carry their whole experiment: ~250 GB
duplicated, every sample mixing all four barcodes. Per-replicate samples needed a 71.2 GB
local round trip.

**The size gate reads the wrong number.** :mod:`lib.import_size` is fed the bytes of what was
requested. For a run accession that is the run's own size, so a 26-run sheet looks like 71 GB
when it will pull nearer 250 GB. A ceiling checked against the wrong figure is not a ceiling.

Pure. The caller supplies ENA's run-to-experiment mapping and per-experiment run sizes.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.results import ERROR, WARNING, Finding as Check


#: Accession prefixes that denote a RUN rather than an experiment.
_RUN_PREFIXES = ("SRR", "ERR", "DRR")




def is_run_accession(accession: str) -> bool:
    return str(accession or "").strip().upper().startswith(_RUN_PREFIXES)


def effective_accession(accession: str, parent_of_run: dict) -> str:
    """What the import will actually fetch when asked for ``accession``.

    Unknown accessions are returned unchanged: this is advisory, and inventing a parent that
    was never looked up would be worse than reporting nothing.
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
