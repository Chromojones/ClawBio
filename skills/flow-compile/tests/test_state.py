"""The output-dir contract that lets stages resume instead of re-running.

The current orchestrator makes the user run the same command three times — compile, download,
re-compile, clean, re-compile — because one command owns both `annotation.csv` and the FASTQ
filenames, and the filenames only settle after the reads are on disk. Re-execution *is* the
dependency mechanism.

`state.json` replaces that with an explicit one. Each stage records what it read (as a content
digest), what it wrote, and how it finished. `begin()` returns "already done" when the digest
still matches and every declared output exists, so re-running a completed stage is free and
re-running an *invalidated* one recomputes. Changing an upstream artefact changes the
downstream digest, which is what makes the dependency explicit rather than implicit.

Two failure modes this must not have:

* **A truncated or hand-edited `state.json` must not strand the run.** It carries decisions,
  never data — anything a stage could read from a real artefact it reads from the artefact —
  so the recovery is always "delete it and re-run", and `load()` says so rather than raising.
* **A stage must not be reported complete when its outputs are gone.** A digest match alone is
  not enough; the artefacts have to still be there.

Story: FAILURES.md#state-contract
"""

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402


def _out(tmp_path, name="run"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestLifecycle:
    def test_a_fresh_dir_has_no_stages(self, tmp_path):
        assert st.load(_out(tmp_path)).get("stages") == {}

    def test_record_then_status(self, tmp_path):
        out = _out(tmp_path)
        st.record(out, "04_annotate", st.OK, outputs=[])
        assert st.status(out, "04_annotate") == st.OK

    def test_an_unrun_stage_has_no_status(self, tmp_path):
        assert st.status(_out(tmp_path), "04_annotate") == ""

    def test_state_survives_a_reload(self, tmp_path):
        out = _out(tmp_path)
        st.record(out, "01_study", st.OK, note="8 samples")
        assert st.load(out)["stages"]["01_study"]["note"] == "8 samples"


class TestRequire:
    def test_require_passes_for_a_completed_stage(self, tmp_path):
        out = _out(tmp_path)
        st.record(out, "05_metadata", st.OK)
        st.require(out, "05_metadata")          # must not raise

    def test_require_refuses_an_unrun_stage(self, tmp_path):
        try:
            st.require(_out(tmp_path), "05_metadata")
        except st.PrerequisiteError as exc:
            assert "05_metadata" in str(exc)
            return
        raise AssertionError("expected PrerequisiteError")

    def test_require_refuses_a_gated_stage(self, tmp_path):
        """A gate that was hit is not a completed prerequisite."""
        out = _out(tmp_path)
        st.record(out, "03_barcodes", st.GATED, release="--accept-proposals")
        try:
            st.require(out, "03_barcodes")
        except st.PrerequisiteError as exc:
            assert "--accept-proposals" in str(exc)
            return
        raise AssertionError("expected PrerequisiteError naming the release flag")


class TestReentrancy:
    def test_an_unchanged_stage_is_already_done(self, tmp_path):
        out = _out(tmp_path)
        src = out / "annotation.csv"; src.write_text("a,b\n1,2\n")
        made = out / "out.txt"; made.write_text("x")
        assert st.begin(out, "04", inputs=[src]) is True          # first run proceeds
        st.record(out, "04", st.OK, outputs=["out.txt"], inputs=[src])
        assert st.begin(out, "04", inputs=[src]) is False         # second is a no-op

    def test_changing_an_input_invalidates(self, tmp_path):
        out = _out(tmp_path)
        src = out / "annotation.csv"; src.write_text("a,b\n1,2\n")
        (out / "out.txt").write_text("x")
        st.record(out, "04", st.OK, outputs=["out.txt"], inputs=[src])
        src.write_text("a,b\n9,9\n")
        assert st.begin(out, "04", inputs=[src]) is True

    def test_a_missing_output_invalidates_even_if_inputs_match(self, tmp_path):
        """A digest match is not proof the artefacts survive."""
        out = _out(tmp_path)
        src = out / "in.csv"; src.write_text("x")
        made = out / "out.txt"; made.write_text("y")
        st.record(out, "04", st.OK, outputs=["out.txt"], inputs=[src])
        made.unlink()
        assert st.begin(out, "04", inputs=[src]) is True

    def test_force_always_recomputes(self, tmp_path):
        out = _out(tmp_path)
        src = out / "in.csv"; src.write_text("x")
        (out / "out.txt").write_text("y")
        st.record(out, "04", st.OK, outputs=["out.txt"], inputs=[src])
        assert st.begin(out, "04", inputs=[src], force=True) is True

    def test_args_are_part_of_the_digest(self, tmp_path):
        """Same inputs, different CLI args, is a different computation."""
        out = _out(tmp_path)
        src = out / "in.csv"; src.write_text("x")
        (out / "out.txt").write_text("y")
        st.record(out, "04", st.OK, outputs=["out.txt"], inputs=[src], args=["--paired", "both"])
        assert st.begin(out, "04", inputs=[src], args=["--paired", "second"]) is True


class TestRoute:
    def test_route_round_trips(self, tmp_path):
        out = _out(tmp_path)
        st.set_route(out, line="direct", protocol="eCLIP", reason="in SRA")
        assert st.route(out)["line"] == "direct"

    def test_route_before_06_is_refused(self, tmp_path):
        try:
            st.route(_out(tmp_path))
        except st.PrerequisiteError:
            return
        raise AssertionError("expected PrerequisiteError")


class TestCorruption:
    def test_a_truncated_state_file_is_recoverable_advice_not_a_crash(self, tmp_path):
        out = _out(tmp_path)
        (out / "state.json").write_text('{"schema": 1, "stages": {')
        try:
            st.load(out)
        except st.StateError as exc:
            assert "delete" in str(exc).lower()
            return
        raise AssertionError("expected StateError telling the user how to recover")

    def test_an_unknown_schema_is_refused(self, tmp_path):
        out = _out(tmp_path)
        (out / "state.json").write_text(json.dumps({"schema": 99, "stages": {}}))
        try:
            st.load(out)
        except st.StateError as exc:
            assert "99" in str(exc)
            return
        raise AssertionError("expected StateError naming the schema")
