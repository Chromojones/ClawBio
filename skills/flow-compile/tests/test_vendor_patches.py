"""Two one-line changes inside `lib/vendor/`, and the grep-tests that survive a re-vendor.

`lib/vendor/` is an upstream mirror. Anything we change there is lost the next time it is
re-vendored, and lost silently, so each patch carries a test that fails loudly if it is
reverted. Both patches are one line and both cause silent data corruption when absent.

**removespace and the `/`.** It replaced both spaces and slashes with underscores in FASTQ
header lines. For a header whose UMI sits in the comment field, that turns

    @SRR123.1 1:N:0:CTACGCTCTAAA/1   ->   @SRR123.1_1:N:0:CTACGCTCTAAA_1

and the last `_`-delimited field is then a constant `1` on every read in the file. UMI-collapse
keys on that field, so every read looks like a duplicate of every other and the library
collapses to near nothing. Leaving `/` alone makes the last field `CTACGCTCTAAA/1`, which
varies per read, which is the UMI. Spaces still must go: the SAM QNAME ends at the first one.

**The `paired` hardcode.** `"paired": "both"` was written into the analysis payload, so a
protocol needing a specific mate silently got both. For eCLIP the crosslink is on read 2; a
run with both mates completes cleanly and puts peaks in the wrong places.

Story: FAILURES.md#vendor-patches
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
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


class TestTheGrepsThatSurviveAReVendor:
    def test_removespace_does_not_replace_slashes(self):
        """A re-vendor restores `.replace('/', '_')`. This is what notices.

        Checked against the assignment itself rather than the file text: the docstring
        deliberately quotes the upstream line it is warning about, and a whole-file grep
        cannot tell the warning from the bug.
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


class TestVendorPatchesAreRecorded:
    def test_the_readme_lists_them(self):
        """A re-vendor is done by a person who needs to know what to reapply."""
        readme = SKILL_DIR / "lib" / "vendor" / "README.md"
        assert readme.exists(), "lib/vendor/README.md is missing"
        text = readme.read_text()
        assert "removespace" in text
        assert "paired" in text
