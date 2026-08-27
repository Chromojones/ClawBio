"""An SRA-direct import has a size ceiling, and hitting it looks like an outage.

GSE63262 (Drosophila SR proteins) is **132.7 GB across 36 runs** — by far the largest study
attempted. Submitted as one import it died with::

    ERROR ~ Error executing process > 'NFCORE_FETCHNGS:FETCHNGS:SRA_FASTQ_FTP (SRX765636_SRR1659972)'
    Caused by: error exit status (4)

32 fetch processes completed, 36 errored or failed. `exit status 4` is wget's *network
failure* code, so the message points squarely at ENA — and ENA was fine: a byte-range fetch
of that exact file returned `206` in 1.1 s, and the ENA API returned `200`, both from this
machine minutes after the job died. Half the fetches in the same job succeeded against the
same host. The study was simply too big to pull in one execution.

Two ways this wastes a day if ungated:

1. **The reported reason is never the real one.** Flow surfaced *"Nextflow 26.04.6 is
   available - Please consider updating your version to it"* as the failure message. That is
   the fifth study where that version notice masked the actual cause. Believing it sends you
   to upgrade Nextflow.
2. **`exit status 4` reads as "ENA is down".** The previous time an import died in
   `SRA_FASTQ_FTP` (E-MTAB-2700) EBI genuinely *was* down, so the identical signature has a
   precedent that makes the wrong diagnosis feel confirmed. Reachability must be tested
   before the size explanation is discarded.

The check is therefore on **total bytes per import job**, not run count: 36 runs is
unremarkable, 132.7 GB is not.

Measured, on this Flow instance:

=====================  ==========  ========
study                  bytes       outcome
=====================  ==========  ========
E-MTAB-2700 (24 smp)   ~0.2 GB     imported
GSE252683 (12 runs)    ~8 GB       imported
GSE63262 (36 runs)     132.7 GB    FAILED
=====================  ==========  ========

So the ceiling is bounded *between* 8 GB and 132.7 GB and is not otherwise known. The module
must not invent a precise limit it cannot support — it warns above the largest success and
refuses only above the known failure, and the batch splitter keeps replicates of a protein
together so a partial import never strands one replicate of a pair.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_guards import (  # noqa: E402
    ERROR,
    WARNING,
    LARGEST_KNOWN_GOOD_BYTES,
    KNOWN_FAILURE_BYTES,
    check_import_size,
    split_into_batches,
    total_bytes,
)

GB = 1_000_000_000

#: GSE63262's true total across all 36 runs, summed from ENA `fastq_bytes`.
GSE63262_BYTES = 132_689_117_735

#: GSE63262 batch 1 (B52 + Rbp1, both replicates) — imported successfully in ~28 minutes
#: after the whole study failed. The largest import measured to work.
GSE63262_BATCH1_BYTES = 32_588_391_652


def rows(*specs):
    """`(accession, target)` pairs in sheet shape."""
    return [{"accession": a, "purification_target": t, "name": f"{t}_rep"} for a, t in specs]


class TestTotalBytes:
    def test_runs_of_one_experiment_are_summed(self):
        """SRX765636 has three runs; the sheet row is one sample."""
        sizes = {"SRR1": 1 * GB, "SRR2": 2 * GB, "SRR3": 3 * GB}
        by_accession = {"SRX765636": sizes}
        assert total_bytes(rows(("SRX765636", "Rbp1")), by_accession) == 6 * GB

    def test_both_mates_of_a_paired_run_are_counted(self):
        """ENA reports `fastq_bytes` as `R1;R2` — counting only R1 halves the estimate."""
        by_accession = {"SRX1": {"SRR1": [2 * GB, 2 * GB]}}
        assert total_bytes(rows(("SRX1", "P")), by_accession) == 4 * GB

    def test_an_accession_with_no_size_is_not_silently_zero(self):
        """Missing sizes must not make a huge study look small."""
        checks = check_import_size(rows(("SRX1", "P"), ("SRX2", "Q")), {"SRX1": {"SRR1": 1 * GB}})
        assert any(c.severity == ERROR and "SRX2" in c.message for c in checks)


class TestTheCeiling:
    def test_the_gse63262_import_is_refused(self):
        by_accession = {f"SRX{i}": {f"SRR{i}": 3.7 * GB} for i in range(36)}
        checks = check_import_size(rows(*[(f"SRX{i}", "SR") for i in range(36)]), by_accession)
        assert any(c.severity == ERROR for c in checks)

    def test_the_refusal_names_size_not_the_network(self):
        """The whole point is to pre-empt the `exit status 4` misdiagnosis."""
        by_accession = {f"SRX{i}": {f"SRR{i}": 3.7 * GB} for i in range(36)}
        message = " ".join(c.message for c in check_import_size(
            rows(*[(f"SRX{i}", "SR") for i in range(36)]), by_accession))
        assert "132" in message or "133" in message
        assert "batch" in message.lower()

    def test_a_batch_the_size_of_the_one_that_worked_passes_clean(self):
        """32.6 GB imported successfully, so it must not warn."""
        by_accession = {"SRX0": {"SRR0": GSE63262_BATCH1_BYTES}}
        assert check_import_size(rows(("SRX0", "B52")), by_accession) == []

    def test_a_study_the_size_of_gse252683_passes_clean(self):
        by_accession = {f"SRX{i}": {f"SRR{i}": 0.6 * GB} for i in range(12)}  # 7.2 GB, at GSE252683 scale
        assert check_import_size(rows(*[(f"SRX{i}", "P") for i in range(12)]), by_accession) == []

    def test_between_known_good_and_known_bad_warns_rather_than_refusing(self):
        """The ceiling is bounded, not measured. Claiming a precise limit would be a guess."""
        by_accession = {"SRX1": {"SRR1": 60 * GB}}
        checks = check_import_size(rows(("SRX1", "P")), by_accession)
        assert [c.severity for c in checks] == [WARNING]
        assert "not known" in " ".join(c.message for c in checks).lower()

    def test_the_bounds_are_the_measured_ones(self):
        assert LARGEST_KNOWN_GOOD_BYTES == GSE63262_BATCH1_BYTES
        assert KNOWN_FAILURE_BYTES == GSE63262_BYTES

    def test_the_exact_study_that_failed_is_refused(self):
        """The regression case, at its true size — not a rounded stand-in.

        The first cut of this module set the threshold to a tidied `132_700_000_000`. The
        study's real total is `132_689_117_735`, 10.9 million bytes below it, so GSE63262 —
        the failure the module exists to prevent — only warned. The test fixture said
        36 x 3.7 GB, which rounds *up* past the threshold and hid it. Only running the check
        against the actual sheet exposed it.

        Bounds must be measured values, never tidied ones.
        """
        by_accession = {"SRX0": {"SRR0": GSE63262_BYTES}}
        checks = check_import_size(rows(("SRX0", "SR")), by_accession)
        assert any(c.severity == ERROR for c in checks)


class TestSplitting:
    def test_a_split_study_yields_batches_under_the_limit(self):
        by_accession = {f"SRX{i}": {f"SRR{i}": 3.7 * GB} for i in range(36)}
        sheet = rows(*[(f"SRX{i}", f"P{i // 2}") for i in range(36)])
        batches = split_into_batches(sheet, by_accession, limit=35 * GB)
        assert len(batches) > 1
        for batch in batches:
            assert total_bytes(batch, by_accession) <= 35 * GB

    def test_every_sample_lands_in_exactly_one_batch(self):
        by_accession = {f"SRX{i}": {f"SRR{i}": 3.7 * GB} for i in range(36)}
        sheet = rows(*[(f"SRX{i}", f"P{i // 2}") for i in range(36)])
        seen = [r["accession"] for b in split_into_batches(sheet, by_accession, limit=35 * GB) for r in b]
        assert sorted(seen) == sorted(r["accession"] for r in sheet)

    def test_replicates_of_a_protein_stay_together(self):
        """Splitting a pair strands one replicate if the second batch fails."""
        by_accession = {f"SRX{i}": {f"SRR{i}": 10 * GB} for i in range(4)}
        sheet = rows(("SRX0", "B52"), ("SRX1", "B52"), ("SRX2", "Rbp1"), ("SRX3", "Rbp1"))
        for batch in split_into_batches(sheet, by_accession, limit=25 * GB):
            targets = {r["purification_target"] for r in batch}
            for target in targets:
                in_batch = sum(1 for r in batch if r["purification_target"] == target)
                in_sheet = sum(1 for r in sheet if r["purification_target"] == target)
                assert in_batch == in_sheet, f"{target} was split across batches"

    def test_a_single_sample_over_the_limit_is_its_own_batch_not_dropped(self):
        by_accession = {"SRX0": {"SRR0": 50 * GB}}
        batches = split_into_batches(rows(("SRX0", "P")), by_accession, limit=35 * GB)
        assert [len(b) for b in batches] == [1]
