"""The four things that must be true before a sheet is submitted, and the one they got wrong.

`import_size`, `run_expansion`, `sample_type_fields` and `paired_selection` all answer "is this
sheet safe to submit?" and all three of the first carried their own `Check` dataclass. Merging
them is mostly tidying, with one exception that is not tidying at all:

**The size gate counted the wrong bytes.** `total_bytes()` sums the size of each accession *as
written in the sheet*. But asking Flow for a run accession imports its entire parent experiment
— verified on GSE78030, where importing `SRR3175580` produced one sample carrying all four runs
of `SRX1590001`, 10.07 GB rather than the requested run. `run_expansion` knew this and the size
gate did not, so a sheet of run accessions was measured at a fraction of what it would actually
transfer, and the 132.7 GB ceiling that GSE63262 taught us could be walked straight past.

The two modules were written a week apart and never introduced. This merge introduces them:
`check_import_size` now measures *effective* bytes.

Story: FAILURES.md#import-guards
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_guards import (  # noqa: E402
    DEFAULT_BATCH_BYTES,
    KNOWN_FAILURE_BYTES,
    LARGEST_KNOWN_GOOD_BYTES,
    check_import_size,
    check_paired_selection,
    check_upload_fields,
    effective_bytes,
    split_into_batches,
    strip_rejected,
    total_bytes,
)
from lib.results import ERROR  # noqa: E402

#: SRX1590001 has four runs; SRR3175580 is one of them. Sizes are the measured ones.
PARENT_OF_RUN = {"SRR3175580": "SRX1590001"}
RUNS_BY_EXPERIMENT = {"SRX1590001": {
    "SRR3175580": 2_500_000_000, "SRR3175581": 2_500_000_000,
    "SRR3175582": 2_500_000_000, "SRR3175583": 2_570_000_000,
}}
BY_ACCESSION = {
    "SRR3175580": {"fastq_bytes": 2_500_000_000},
    "SRX1590001": {"fastq_bytes": 10_070_000_000},
}


class TestTheSizeGateMeasuresWhatIsActuallyTransferred:
    def test_a_run_row_is_measured_as_its_experiment(self):
        """The whole point: asking for one run imports all four."""
        got = total_bytes(
            [{"accession": "SRR3175580"}], BY_ACCESSION,
            parent_of_run=PARENT_OF_RUN, runs_by_experiment=RUNS_BY_EXPERIMENT,
        )
        assert got == 10_070_000_000

    def test_without_expansion_data_it_still_counts_the_row(self):
        """Callers that cannot resolve parents must not silently get zero."""
        assert total_bytes([{"accession": "SRR3175580"}], BY_ACCESSION) == 2_500_000_000

    def test_effective_bytes_agrees(self):
        assert effective_bytes("SRR3175580", PARENT_OF_RUN, RUNS_BY_EXPERIMENT) == 10_070_000_000

    def test_an_experiment_row_is_unchanged_by_expansion(self):
        assert total_bytes(
            [{"accession": "SRX1590001"}], BY_ACCESSION,
            parent_of_run=PARENT_OF_RUN, runs_by_experiment=RUNS_BY_EXPERIMENT,
        ) == 10_070_000_000

    def test_expansion_can_push_a_sheet_over_the_ceiling(self):
        """The failure this merge prevents: 20 runs measured small, imported large."""
        by_acc, parents, runs = {}, {}, {}
        rows = []
        for i in range(20):
            run, exp = f"SRR{i:07d}", f"SRX{i:07d}"
            rows.append({"accession": run})
            by_acc[run] = {"fastq_bytes": 2_000_000_000}
            by_acc[exp] = {"fastq_bytes": 8_000_000_000}
            parents[run], runs[exp] = exp, {run: 8_000_000_000}
        naive = check_import_size(rows, by_acc)
        assert [c for c in naive if c.severity == ERROR] == []      # 40 GB, looks fine
        real = check_import_size(rows, by_acc, parent_of_run=parents, runs_by_experiment=runs)
        assert [c for c in real if c.severity == ERROR] != []       # 160 GB, refused


class TestTheCeilingItself:
    def test_the_measured_failure_is_refused(self):
        rows = [{"accession": "SRX1"}]
        by_acc = {"SRX1": {"fastq_bytes": KNOWN_FAILURE_BYTES}}
        assert [c for c in check_import_size(rows, by_acc) if c.severity == ERROR]

    def test_the_largest_success_is_not_refused(self):
        rows = [{"accession": "SRX1"}]
        by_acc = {"SRX1": {"fastq_bytes": LARGEST_KNOWN_GOOD_BYTES}}
        assert [c for c in check_import_size(rows, by_acc) if c.severity == ERROR] == []

    def test_an_unknown_size_is_an_error_not_a_zero(self):
        assert [c for c in check_import_size([{"accession": "SRX9"}], {}) if c.severity == ERROR]

    def test_batches_respect_the_limit(self):
        by_acc = {f"SRX{i}": {"fastq_bytes": 10_000_000_000} for i in range(10)}
        rows = [{"accession": f"SRX{i}", "purification_target": f"RBP{i}"} for i in range(10)]
        batches = split_into_batches(rows, by_acc, limit=DEFAULT_BATCH_BYTES)
        assert len(batches) > 1
        for batch in batches:
            assert total_bytes(batch, by_acc) <= DEFAULT_BATCH_BYTES

    def test_a_targets_replicates_are_never_split(self):
        """If a later batch fails, a whole protein is missing and obvious; half a pair is not."""
        by_acc = {f"SRX{i}": {"fastq_bytes": 10_000_000_000} for i in range(6)}
        rows = [{"accession": f"SRX{i}", "purification_target": f"RBP{i // 3}"} for i in range(6)]
        for batch in split_into_batches(rows, by_acc, limit=DEFAULT_BATCH_BYTES):
            targets = {r["purification_target"] for r in batch}
            for target in targets:
                everywhere = sum(r["purification_target"] == target for r in rows)
                assert sum(r["purification_target"] == target for r in batch) == everywhere

    def test_one_oversized_group_becomes_its_own_batch(self):
        """Dropping it would be worse than exceeding the limit; check_import_size already warned."""
        by_acc = {f"SRX{i}": {"fastq_bytes": 40_000_000_000} for i in range(2)}
        rows = [{"accession": f"SRX{i}", "purification_target": "RBP1"} for i in range(2)]
        assert len(split_into_batches(rows, by_acc, limit=DEFAULT_BATCH_BYTES)) == 1


class TestSampleTypeFields:
    def test_strandedness_is_rejected_for_clip(self):
        assert check_upload_fields({"strandedness": "unstranded"}, sample_type="CLIP")

    def test_stripping_leaves_the_rest_intact(self):
        row = strip_rejected({"name": "S1", "strandedness": "unstranded"}, sample_type="CLIP")
        assert row == {"name": "S1"}


class TestPairedSelection:
    def test_second_on_single_end_is_refused(self):
        assert check_paired_selection("second", layouts={"SINGLE"}).ok is False

    def test_second_on_paired_end_is_fine(self):
        assert check_paired_selection("second", layouts={"PAIRED"}).ok is True


class TestShims:
    def test_old_paths_still_import(self):
        from lib.import_guards import check_import_size as a
        from lib.import_guards import check_paired_selection as b
        from lib.import_guards import effective_bytes as c
        from lib.import_guards import strip_rejected as d

        assert (a, b, c, d) == (check_import_size, check_paired_selection,
                                effective_bytes, strip_rejected)
