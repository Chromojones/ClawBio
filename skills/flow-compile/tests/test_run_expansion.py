"""Asking for a run gets you its whole experiment, and the job says COMPLETED.

`flowbio samples import` accepts a run accession and silently substitutes its parent
experiment. Measured on GSE78030::

    requested SRR3175580              2,213,904,326 bytes   (1 run)
    delivered SRX1590001              10,075,864,988 bytes  (4 runs)
    job status                        COMPLETED

ENA is not the cause and neither is fetchngs: `filereport?accession=SRR3175580&result=read_run`
returns exactly one row, which is the same endpoint fetchngs resolves against. The
substitution happens in Flow's wrapper.

Two consequences, both of which cost real time before they were understood.

**Per-run samples are unreachable through import.** GSE78030's 7 experiments hold 26 runs
(4+4+4+4+4+3+3), one biological replicate each. Importing 26 SRRs would have produced 26
samples each carrying its entire experiment: ~250 GB duplicated, every sample mixing all four
barcodes. The only route to per-replicate samples was a 71.2 GB local round-trip.

**The size gate reads the wrong number.** `import_size` is fed the bytes of what was
requested. For a run accession that is the run's own size, so a sheet of 26 runs looks like
71 GB when it will actually pull ~250 GB. A ceiling checked against the wrong figure is not a
ceiling.

So before submitting, every run accession is resolved to its parent and the sheet is costed on
what will actually arrive, not on what was asked for.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.run_expansion import (  # noqa: E402
    ERROR,
    WARNING,
    check_run_expansion,
    effective_accession,
    effective_bytes,
)

# Verbatim from ENA for GSE78030.
GSE78030 = {
    "SRX1590001": {"SRR3175580": 2_213_904_326, "SRR3175581": 2_803_733_533,
                   "SRR3175582": 2_418_356_845, "SRR3175583": 2_639_870_284},
    "SRX1590006": {"SRR3175600": 1_000_000_000, "SRR3175601": 1_000_000_000,
                   "SRR3175602": 1_000_000_000},
}
PARENT = {run: srx for srx, runs in GSE78030.items() for run in runs}


class TestResolution:
    def test_a_run_resolves_to_its_parent(self):
        assert effective_accession("SRR3175580", PARENT) == "SRX1590001"

    def test_an_experiment_resolves_to_itself(self):
        assert effective_accession("SRX1590001", PARENT) == "SRX1590001"

    def test_an_unknown_accession_is_returned_unchanged(self):
        """Resolution is advisory; it must not invent a parent it did not look up."""
        assert effective_accession("SRR9999999", PARENT) == "SRR9999999"


class TestCosting:
    def test_a_run_is_costed_at_its_parents_size(self):
        """The whole point: 2.2 GB requested, 10.1 GB delivered."""
        assert effective_bytes("SRR3175580", PARENT, GSE78030) == 10_075_864_988

    def test_an_experiment_is_costed_at_its_own_size(self):
        assert effective_bytes("SRX1590001", PARENT, GSE78030) == 10_075_864_988

    def test_the_naive_figure_is_the_one_that_misleads(self):
        naive = GSE78030["SRX1590001"]["SRR3175580"]
        assert effective_bytes("SRR3175580", PARENT, GSE78030) > naive * 4


class TestTheCheck:
    def test_a_run_whose_parent_has_siblings_is_refused(self):
        checks = check_run_expansion(["SRR3175580"], PARENT, GSE78030)
        assert any(c.severity == ERROR for c in checks)

    def test_the_refusal_names_both_accessions_and_the_real_size(self):
        message = " ".join(c.message for c in check_run_expansion(["SRR3175580"], PARENT, GSE78030))
        assert "SRR3175580" in message and "SRX1590001" in message
        assert "10.1" in message or "10,075,864,988" in message

    def test_it_says_per_run_import_is_impossible(self):
        message = " ".join(c.message for c in check_run_expansion(["SRR3175580"], PARENT, GSE78030))
        assert "local" in message.lower()

    def test_a_run_that_is_its_experiments_only_run_only_warns(self):
        """Nothing extra is delivered, so it is not an error, but the substitution still
        happens and the sheet should name the experiment."""
        single = {"SRX2": {"SRR2": 500}}
        checks = check_run_expansion(["SRR2"], {"SRR2": "SRX2"}, single)
        assert checks and all(c.severity == WARNING for c in checks)

    def test_experiment_accessions_pass_clean(self):
        assert check_run_expansion(["SRX1590001", "SRX1590006"], PARENT, GSE78030) == []

    def test_two_runs_of_the_same_experiment_are_reported_once_as_a_duplicate(self):
        """Importing both delivers the same experiment twice."""
        checks = check_run_expansion(["SRR3175580", "SRR3175581"], PARENT, GSE78030)
        message = " ".join(c.message for c in checks)
        assert "twice" in message.lower() or "duplicate" in message.lower()
