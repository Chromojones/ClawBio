"""`batch-template` lists a field as required that the API refuses for that sample type.

    $ flowbio samples batch-template --sample-type CLIP
    Required columns: name, reads1, five_prime_barcode_sequence, purification_target, strandedness

Supplying exactly that set to `samples upload` returns::

    Error: {'strandedness': ['Not a valid attribute for this sample type.']}

`strandedness` is RNA-Seq only. The template says CLIP requires it, the API rejects it, and
both are shipped by the same client. Ten E-MTAB-13331 uploads failed on it in one batch, and
the same contradiction is recorded in this skill's own design notes from the PARP13 run
months earlier, which is the point: knowing it is not enough, because the template is the
thing you naturally trust when building a sheet.

The failure is at least loud. What makes it worth a guard is the cost shape: `samples upload`
takes one sample per call, so the rejection arrives after the reads have been transferred,
and it repeats for every sample in the batch.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.sample_type_fields import (  # noqa: E402
    ERROR,
    REJECTED_BY_SAMPLE_TYPE,
    check_upload_fields,
    strip_rejected,
)


class TestTheKnownContradiction:
    def test_strandedness_is_rejected_for_clip(self):
        assert "strandedness" in REJECTED_BY_SAMPLE_TYPE["CLIP"]

    def test_a_clip_sheet_carrying_it_is_refused(self):
        checks = check_upload_fields({"name": "x", "reads1": "a.fq.gz",
                                      "strandedness": "forward"}, sample_type="CLIP")
        assert any(c.severity == ERROR for c in checks)

    def test_the_message_says_the_template_is_wrong(self):
        message = " ".join(c.message for c in check_upload_fields(
            {"strandedness": "forward"}, sample_type="CLIP"))
        assert "template" in message.lower()
        assert "rna-seq" in message.lower()

    def test_rna_seq_keeps_it(self):
        assert check_upload_fields({"name": "x", "strandedness": "forward"},
                                   sample_type="RNA-Seq") == []

    def test_case_and_spelling_of_the_sample_type(self):
        for spelling in ("CLIP", "clip"):
            assert check_upload_fields({"strandedness": "f"}, sample_type=spelling) != []


class TestStripping:
    def test_it_removes_only_the_rejected_field(self):
        row = {"name": "x", "reads1": "a.fq.gz", "strandedness": "forward",
               "purification_target": "SON"}
        out = strip_rejected(row, sample_type="CLIP")
        assert "strandedness" not in out
        assert out["purification_target"] == "SON" and out["name"] == "x"

    def test_it_leaves_rna_seq_untouched(self):
        row = {"name": "x", "strandedness": "forward"}
        assert strip_rejected(row, sample_type="RNA-Seq") == row

    def test_an_unknown_sample_type_is_left_alone(self):
        """Do not invent rules for types we have not observed being refused."""
        row = {"name": "x", "strandedness": "forward"}
        assert strip_rejected(row, sample_type="ATAC-Seq") == row

    def test_the_original_row_is_not_mutated(self):
        row = {"name": "x", "strandedness": "forward"}
        strip_rejected(row, sample_type="CLIP")
        assert "strandedness" in row


class TestEmptyValues:
    def test_an_empty_rejected_field_is_still_refused(self):
        """`samples upload` sends whatever the sheet names; an empty string is still the
        attribute, and the API refuses on the key rather than the value."""
        assert check_upload_fields({"strandedness": ""}, sample_type="CLIP") != []

    def test_absent_is_fine(self):
        assert check_upload_fields({"name": "x", "reads1": "a.fq.gz"},
                                   sample_type="CLIP") == []
