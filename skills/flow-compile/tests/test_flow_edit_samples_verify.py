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

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.vendor.flow_api.metadata.flow_edit_samples import live_value  # noqa: E402

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
