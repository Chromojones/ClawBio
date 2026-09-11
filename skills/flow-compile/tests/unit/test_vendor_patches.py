"""Two lines in `lib/vendor/` that corrupt data silently if reverted.

`removespace` keeps `/`: replacing it makes the last `_` field of
`@SRR123.1 1:N:0:CTACGCTCTAAA/1` a constant `1`, and UMI deduplication collapses the library.
Spaces still go, since the SAM QNAME ends at the first. The analysis payload does not hardcode
`paired`, which decides the mate analysed.

Story: FAILURES.md#vendor-patches
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

REMOVESPACE = SKILL_DIR / "lib" / "vendor" / "flow_api" / "preprocessing" / "removespace.py"
ANALYSIS = SKILL_DIR / "lib" / "vendor" / "flow_api" / "analysis" / "flowrunanalysis_flowbio.py"

#: A CSDE1-shaped header: the UMI rides in the comment field, after the space.
CSDE1_HEADERS = [
    "@SRR12345.1 1:N:0:CTACGCTCTAAA/1",
    "@SRR12345.2 1:N:0:GGACTTGCAATC/1",
    "@SRR12345.3 1:N:0:TTCAGGATCCGA/1",
]


def _clean(line):
    import importlib.util

    spec = importlib.util.spec_from_file_location("removespace", REMOVESPACE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._clean_header_line(line).decode().strip()


class TestRemovespaceKeepsTheSlash:
    def test_the_last_field_varies_across_reads(self):
        """The whole point: a constant final field collapses the library."""
        finals = {_clean(h).split("_")[-1] for h in CSDE1_HEADERS}
        assert len(finals) == len(CSDE1_HEADERS), f"final fields collapsed to {finals}"

    def test_the_umi_survives_in_the_last_field(self):
        """The field is the whole comment, `1:N:0:<UMI>/1`; what matters is the UMI is in it."""
        last = _clean(CSDE1_HEADERS[0]).split("_")[-1]
        assert last == "1:N:0:CTACGCTCTAAA/1"
        assert "CTACGCTCTAAA" in last

    def test_spaces_are_still_replaced(self):
        """The SAM QNAME ends at the first space, so these genuinely must go."""
        assert " " not in _clean(CSDE1_HEADERS[0])

    def test_the_slash_is_preserved(self):
        assert "/" in _clean(CSDE1_HEADERS[0])


class TestTheLinesThemselves:
    def test_removespace_does_not_replace_slashes(self):
        """An "obvious" cleanup would restore `.replace('/', '_')`.

        Checked on the assignment, not the file text, so prose quoting the line cannot trip it.
        """
        code = [
            line.strip() for line in REMOVESPACE.read_text().splitlines()
            if line.strip().startswith("s = text.strip()")
        ]
        assert code == ["s = text.strip().replace(' ', '_')"], code

    def test_the_paired_hardcode_is_gone(self):
        assert '"paired": "both"' not in ANALYSIS.read_text()

    def test_paired_is_read_from_the_params(self):
        assert "paired" in ANALYSIS.read_text()



class TestTheRunnerNeverPromptsAnAgent:
    """`run_analysis.sh` is run by the agent. A login that falls back to `input()` hangs it."""

    def _module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("runner", ANALYSIS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_token_in_the_environment_is_used(self, monkeypatch):
        runner = self._module()
        for key in ("FLOWBIO_USERNAME", "FLOWBIO_PASSWORD", "FLOW_TOKEN"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("FLOW_API_TOKEN", "tok")

        class NoHTTP:
            def post(self, *a, **k):
                raise AssertionError("a token was set, so no login call should be made")

        assert runner.rest_login(NoHTTP()) == "tok"

    def test_no_credentials_without_a_terminal_fails_instead_of_prompting(self, monkeypatch, tmp_path):
        import io

        import pytest

        runner = self._module()
        for key in ("FLOWBIO_USERNAME", "FLOWBIO_PASSWORD", "FLOW_API_TOKEN", "FLOW_TOKEN"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("FLOW_TOKEN_FILE", str(tmp_path / "no-token"))
        monkeypatch.setattr("sys.stdin", io.StringIO(""))

        def prompted(*a, **k):
            raise AssertionError("prompted for credentials with no terminal attached")

        monkeypatch.setattr("builtins.input", prompted)
        with pytest.raises(RuntimeError, match="FLOWBIO_USERNAME"):
            runner.rest_login(object())
