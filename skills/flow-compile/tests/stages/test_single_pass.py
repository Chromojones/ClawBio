"""The annotation is built once, because nothing renames the reads any more.

The old orchestrator asked the user to run the same command three times, and the reason was
specific: header cleaning rewrote every FASTQ to `*.cleaned.fastq.gz`, so the annotation
sheet's `File` column was stale the moment cleaning ran. `_apply_cleaned_filenames` rebuilt the
column against the new names, and the second `apply_eclip_crosslink_mate_filenames` call sat
directly after it for the same reason. The sheet had to be rebuilt because the files had been
renamed.

`removespace` now runs inside the clip-seq pipeline. Nothing renames anything locally, the
filenames chosen at annotation time are the filenames uploaded, and the metadata can be built
in a single pass.

That only stays true while exactly one stage writes annotation content. Two writers of the
`File` column is how the loop started, so it is checked rather than intended.

Story: FAILURES.md#state-contract
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

STAGES = sorted(p for p in (SKILL_DIR / "stages").glob("*.py") if not p.name.startswith("_"))


class TestOneWriter:
    def test_exactly_one_stage_writes_the_annotation(self):
        """Reading it is fine and several stages do; writing it must be one place.

        The first version of this test asked which files mentioned both the filename and
        `to_csv` anywhere, which flagged 210_upload for reading the annotation and writing a
        different sheet.
        """
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
