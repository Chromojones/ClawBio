"""Post-edit verification must read metadata where Flow actually stores it.

`flow_edit_samples.py` verified with `live.get(key)`, but the sample API nests everything:

    {"metadata": {"source": {"value": "Brain", "annotation": "Postnatal"}}}

so `live.get("source__annotation")` is always None and `live.get("source")` is a dict, never
the string that was sent. Every metadata edit therefore logged "verify mismatch" even when it
had applied perfectly (observed on all 3 E-MTAB-1008 samples). That is worse than no check:
it trains the operator to ignore the warning that is supposed to catch a real failure.

This is the same nesting trap that made an earlier session report "all tags empty" on
GSE290281 when 17 samples in fact carried `cV5`.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.vendor.flow_api.metadata.flow_edit_samples import (  # noqa: E402
    CLEAR_SENTINEL,
    WHITELIST_EDIT_FIELDS,
    build_edit_body,
    live_value,
)

# Shape returned by GET /samples/{id}, trimmed to what verification touches.
LIVE = {
    "id": "609008388829402019",
    "name": "Nova_Mm_BrainA_Rep2_ERR102558",
    "metadata": {
        "source": {"value": "Brain", "annotation": "Postnatal"},
        "purification_target": {"value": "Nova", "annotation": ""},
        "purification_agent": {"value": "Anti-NOVA (gift: Robert B Darnell)"},
    },
}


class TestLiveValue:
    def test_annotation_is_read_from_the_nested_annotation_slot(self):
        assert live_value(LIVE, "source__annotation") == "Postnatal"

    def test_plain_metadata_field_is_read_from_the_nested_value_slot(self):
        assert live_value(LIVE, "source") == "Brain"
        assert live_value(LIVE, "purification_target") == "Nova"

    def test_top_level_field_still_resolves(self):
        """`name` is not nested under metadata."""
        assert live_value(LIVE, "name") == "Nova_Mm_BrainA_Rep2_ERR102558"

    def test_empty_annotation_reads_as_empty_not_missing(self):
        assert live_value(LIVE, "purification_target__annotation") == ""

    def test_absent_annotation_slot_is_empty(self):
        """Agent has no annotation key at all — that is an empty annotation, not a crash."""
        assert live_value(LIVE, "purification_agent__annotation") == ""

    def test_unknown_field_is_none(self):
        assert live_value(LIVE, "nonexistent_field") is None

    def test_sample_without_a_metadata_block_does_not_crash(self):
        assert live_value({"name": "x"}, "source") is None
        assert live_value({"name": "x"}, "source__annotation") == ""


class TestClearingAField:
    """A field must be clearable, because "empty" is a real value in this database.

    Controls carry an EMPTY `purification_agent` by convention, and a size-matched input
    carries no tag. Correcting GSE290281's 8 mislabelled inputs therefore means *removing*
    the IP's antibody and its `cV5` tag — but `row_to_body` dropped every empty value, so
    those two edits vanished silently and the dry run showed only the name change.

    Blanket-dropping empties is the right default (a sparse CSV must not wipe columns it
    leaves blank), so clearing needs to be explicit rather than inferred from "".
    """

    def test_blank_cell_is_still_ignored(self):
        """Sparse CSVs stay safe — this is why "" cannot itself mean 'clear'."""
        assert build_edit_body({"name": "x", "purification_agent": ""}) == {"name": "x"}

    def test_sentinel_clears_the_field(self):
        body = build_edit_body({"name": "x", "purification_agent": CLEAR_SENTINEL})
        assert body == {"name": "x", "purification_agent": ""}

    def test_sentinel_is_case_insensitive_and_trimmed(self):
        assert build_edit_body({"purification_agent": "  __clear__ "}) == {"purification_agent": ""}

    def test_sentinel_works_for_annotation_fields(self):
        body = build_edit_body({"purification_target__annotation": CLEAR_SENTINEL})
        assert body == {"purification_target__annotation": ""}

    def test_ordinary_values_are_untouched(self):
        body = build_edit_body({"purification_target": "SMInput", "name": "RNPS1_INPUT_rep1"})
        assert body == {"purification_target": "SMInput", "name": "RNPS1_INPUT_rep1"}

    def test_non_whitelisted_columns_are_still_excluded(self):
        assert "sample_id" not in build_edit_body({"sample_id": "123", "name": "x"})


class TestPubmedIsATopLevelField:
    """`pubmed` is a sample PROPERTY, not a metadata attribute — and it must be editable.

    It is absent from `samples batch-template --sample-type CLIP`, whose column list covers
    only metadata attributes, which is why it looked as though Flow had no PubMed field and
    PMIDs went into `comments` instead. `POST /samples/{id}/edit {"pubmed": "31216479"}`
    returns 200 and the value lands at the TOP level of the sample, beside `name`.

    It is not cosmetic: setting it populates the owning project's `papers` with a resolved
    citation (title, year, journal). A PMID buried in comments loses that linkage.
    """

    def test_pubmed_is_whitelisted_for_editing(self):
        assert "pubmed" in WHITELIST_EDIT_FIELDS

    def test_pubmed_survives_body_building(self):
        assert build_edit_body({"pubmed": "31216479"}) == {"pubmed": "31216479"}

    def test_pubmed_can_be_cleared(self):
        assert build_edit_body({"pubmed": CLEAR_SENTINEL}) == {"pubmed": ""}

    def test_pubmed_verifies_from_the_top_level_not_metadata(self):
        """`live_value` must find it beside `name`, not under `metadata`."""
        live = {"name": "x", "pubmed": "31216479", "metadata": {"source": {"value": "hNSC"}}}
        assert live_value(live, "pubmed") == "31216479"
