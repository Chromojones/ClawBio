"""A run accession imports its whole experiment, and the job says COMPLETED.

Measured on GSE78030::

    requested SRR3175580     2,213,904,326 bytes   (1 run)
    delivered SRX1590001    10,075,864,988 bytes   (4 runs)

The substitution is Flow's: ENA's filereport returns one run. Per-run samples are unreachable
through import, and the size gate costs a run at its parent's size.

Story: FAILURES.md#import-guards
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.import_guards import (  # noqa: E402
    effective_accession,
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


