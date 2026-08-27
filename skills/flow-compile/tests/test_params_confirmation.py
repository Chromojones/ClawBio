"""Hard stop #4: the confirmed parameters must match the derived ones BY VALUE.

The generated analysis script compared the two files with `cmp -s`, which is a byte
comparison. Two JSON objects holding identical parameters differ byte-for-byte whenever a key
order, an indent, or a trailing newline changes, and any of those is enough to make a correctly
confirmed run refuse to start. The failure runs the other way too: `cmp` reports no difference
between two files that are equally wrong, so a key missing from both passes the gate.

A gate that blocks correct runs is worse than annoying — it teaches the person operating it to
work around the gate, which is exactly what this one is for.

Compared as parsed values now, so key order and formatting are irrelevant and the comparison
is about the parameters themselves.

Story: FAILURES.md#params-confirmation
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.pipeline_params import compare_confirmed_params  # noqa: E402

DERIVED = {"move_umi_to_header": "false", "umi_separator": "rbc:", "paired": "second"}


class TestValueEquality:
    def test_identical_values_match(self):
        assert compare_confirmed_params(DERIVED, dict(DERIVED)).ok

    def test_key_order_does_not_matter(self):
        """`cmp -s` said these differed. They do not."""
        reordered = {k: DERIVED[k] for k in reversed(list(DERIVED))}
        assert compare_confirmed_params(DERIVED, reordered).ok

    def test_a_changed_value_is_caught(self):
        changed = dict(DERIVED, paired="both")
        verdict = compare_confirmed_params(DERIVED, changed)
        assert not verdict.ok
        assert "paired" in verdict.reason

    def test_a_missing_key_is_caught(self):
        missing = {k: v for k, v in DERIVED.items() if k != "paired"}
        verdict = compare_confirmed_params(DERIVED, missing)
        assert not verdict.ok
        assert "paired" in verdict.reason

    def test_an_extra_key_is_caught(self):
        """A confirmed file with a parameter the derivation never produced is not a match."""
        extra = dict(DERIVED, encode_eclip="true")
        verdict = compare_confirmed_params(DERIVED, extra)
        assert not verdict.ok
        assert "encode_eclip" in verdict.reason

    def test_the_reason_names_every_difference(self):
        verdict = compare_confirmed_params(DERIVED, dict(DERIVED, paired="both", umi_separator="_"))
        assert "paired" in verdict.reason and "umi_separator" in verdict.reason


class TestFormattingIsIrrelevant:
    def test_indentation_does_not_matter(self, tmp_path):
        a = tmp_path / "a.json"; a.write_text(json.dumps(DERIVED, indent=2))
        b = tmp_path / "b.json"; b.write_text(json.dumps(DERIVED))
        assert compare_confirmed_params(json.loads(a.read_text()),
                                        json.loads(b.read_text())).ok

    def test_byte_comparison_would_have_disagreed(self, tmp_path):
        """Pins the reason this changed, so nobody restores `cmp -s` as a simplification."""
        a = tmp_path / "a.json"; a.write_text(json.dumps(DERIVED, indent=2, sort_keys=True))
        b = tmp_path / "b.json"; b.write_text(json.dumps(DERIVED))
        assert a.read_bytes() != b.read_bytes()
        assert compare_confirmed_params(json.loads(a.read_text()),
                                        json.loads(b.read_text())).ok


class TestTheGeneratedScript:
    """Checked against the emitted script, not the generator's source.

    The generator carries a comment explaining why `cmp -s` was replaced, and a grep over the
    source cannot tell that explanation from the thing it warns about. This is the second time
    in this rebuild that a grep-test matched its own documentation.
    """

    @pytest.fixture
    def script(self, tmp_path):
        from lib.flow_stages import write_analysis_script

        path = write_analysis_script(
            tmp_path,
            analysis_script=tmp_path / "flowrunanalysis_flowbio.py",
            project_id="P1",
            pipeline_params={"paired": "second"},
            sample_name_filter="",
            experimental_method="eCLIP",
        )
        return path.read_text()

    def test_it_no_longer_byte_compares(self, script):
        executable = [ln for ln in script.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("cmp -s" in ln for ln in executable)

    def test_it_compares_by_value(self, script):
        assert "compare_confirmed_params" in script

    def test_it_still_gates_on_a_missing_confirmation(self, script):
        """The gate itself must survive the change to how the comparison is made."""
        assert "exit 3" in script
