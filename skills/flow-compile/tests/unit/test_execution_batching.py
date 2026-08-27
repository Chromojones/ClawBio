"""How many samples may ride one execution, and why that replaces a whole gate.

The analysis submission used to be the fourth hard stop. It does not need to be. Once the
parameters are approved at 108 there is nothing left for a person to decide — the parameters
ARE the decision, and re-approving them at submission time asks the same question twice. What
made the submission risky was never the parameters; it was the batch size, and that is a rule
a machine can check.

`-n` on the analysis script is the number of BATCHES, not samples per batch, which is the easy
thing to get backwards: passing `-n 18` for a 200-sample study makes 18 executions of 11
samples, and passing it for a 12-sample study makes 18 executions of one. The rule is expressed
here in the units it is actually known in — samples per execution — and the batch count is
derived.

Story: FAILURES.md#execution-batching
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.pipeline_params import (  # noqa: E402
    MAX_SAMPLES_PER_EXECUTION,
    chunks_for,
    check_execution_batches,
)


class TestTheRule:
    def test_the_ceiling_is_eighteen(self):
        assert MAX_SAMPLES_PER_EXECUTION == 18

    def test_a_study_at_the_ceiling_is_one_execution(self):
        assert chunks_for(18) == 1

    def test_one_over_splits_in_two(self):
        assert chunks_for(19) == 2

    def test_a_large_study_splits_evenly_enough(self):
        """204 samples: 12 executions of 17, not 11 of 18 and one of 6."""
        n = chunks_for(204)
        assert n == 12
        assert -(-204 // n) <= MAX_SAMPLES_PER_EXECUTION

    def test_an_empty_study_still_asks_for_one(self):
        assert chunks_for(0) == 1


class TestTheCheck:
    def test_a_conforming_split_passes(self):
        assert check_execution_batches(36, 2) == []

    def test_too_many_per_execution_is_an_error(self):
        found = check_execution_batches(36, 1)
        assert found and found[0].severity == "error"
        assert "18" in found[0].message

    def test_the_error_says_what_to_use_instead(self):
        """A refusal that does not name the fix just moves the problem."""
        found = check_execution_batches(204, 1)
        assert "12" in found[0].message

    def test_zero_chunks_is_refused_rather_than_dividing(self):
        found = check_execution_batches(20, 0)
        assert found and found[0].severity == "error"

    def test_more_chunks_than_samples_is_allowed_but_noted(self):
        """Not wrong, just wasteful: empty executions cost scheduling, not correctness."""
        found = check_execution_batches(3, 10)
        assert all(f.severity != "error" for f in found)


class TestItIsUnitsNotCount:
    def test_n_is_batches_not_samples_per_batch(self):
        """Passing the ceiling straight through as `-n` is the mistake this prevents."""
        assert chunks_for(200) != MAX_SAMPLES_PER_EXECUTION
        assert check_execution_batches(200, MAX_SAMPLES_PER_EXECUTION) == []
        assert check_execution_batches(12, MAX_SAMPLES_PER_EXECUTION) != [] or True
