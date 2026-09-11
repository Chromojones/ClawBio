"""The annotation is built once: exactly one stage writes it, and nothing renames the reads.

Header cleaning runs in the clip-seq pipeline, so the filenames chosen at annotation are the ones
uploaded. A second writer of the `File` column would make the sheet stale.

Story: FAILURES.md#state-contract
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

STAGES = sorted(p for p in (SKILL_DIR / "stages").glob("*.py") if not p.name.startswith("_"))


class TestOneWriter:
    def test_exactly_one_stage_writes_the_annotation(self):
        """Several stages read the annotation; one writes it. 210 writes a different sheet."""
        import re

        writers = [
            p.name for p in STAGES
            if re.search(r'to_csv\(\s*out\s*/\s*"annotation\.raw\.csv"', p.read_text())
        ]
        assert writers == ["04_annotate.py"], writers

    def test_only_that_stage_promotes_the_crosslink_mate(self):
        callers = [p.name for p in STAGES
                   if "apply_eclip_crosslink_mate_filenames(" in p.read_text()]
        assert callers == ["04_annotate.py"], callers


class TestNothingRenamesLocally:
    def test_no_stage_rewrites_filenames_to_cleaned(self):
        """`cleaned_fastq_name` is what made the sheet stale; the pipeline cleans now."""
        offenders = [p.name for p in STAGES if "cleaned_fastq_name" in p.read_text()]
        assert offenders == [], offenders

    def test_no_stage_offers_local_header_cleaning(self):
        """A `--clean-headers` flag would rename the reads and desynchronise the sheet."""
        offenders = [p.name for p in STAGES if "--clean-headers" in p.read_text()]
        assert offenders == [], offenders

    def test_the_local_line_still_records_the_header_state(self):
        """Cleaning moves to the pipeline; classifying the header does not."""
        assert "classify_headers" in (SKILL_DIR / "stages" / "201_fetch.py").read_text()
