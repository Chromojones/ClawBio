"""The metadata gate must reject an over-long `comments`, not leave it to the server.

A 1000-character cap on `comments` has bitten three times: GSE76475 (which produced
`MAX_COMMENTS_CHARS`), GSE58448, and U1A IP1. Each time the constant existed and each time it
was bypassed, because it lives in `lib/sra_import.py` — the module that builds import sheets —
while the sheets in question were assembled by hand and validated with
`validate_annotation_table`, which never looked at comment length.

So the guardrail was real, documented, and silent for the exact workflow that needed it. The
fix is to put the check where the validation actually runs.

Failure mode without it: `samples import` rejects the whole batch, or `samples upload`
rejects every row one at a time — after the reads are already staged.
"""

import sys
from pathlib import Path

import pandas as pd

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import (  # noqa: E402
    ERROR,
    MAX_COMMENTS_CHARS,
    validate_annotation_table,
    validate_comments,
)


def table(comment):
    return pd.DataFrame([{
        "Sample Name": "SNRPA_HeLa_Hs_IP1_rep1", "Protein (Purification Target)": "SNRPA",
        "Purification Target Annotation": "n3xFLAG",
        "Purification Agent": "Anti-FLAG (Sigma F3165)", "Cell or Tissue": "HeLa",
        "Condition": "first IP", "5' Barcode Sequence": "NNNNN", "Organism": "Hs",
        "Comments": comment,
    }])


class TestTheLimit:
    def test_the_constant_is_1000(self):
        assert MAX_COMMENTS_CHARS == 1000

    def test_a_comment_at_the_limit_passes(self):
        assert validate_comments("x" * 1000) == []

    def test_one_character_over_is_an_error(self):
        checks = validate_comments("x" * 1001)
        assert [c.severity for c in checks] == [ERROR]

    def test_the_message_gives_both_numbers(self):
        message = validate_comments("x" * 1182)[0].message
        assert "1182" in message and "1000" in message

    def test_an_empty_comment_is_fine(self):
        assert validate_comments("") == []


class TestWiredIntoTheGate:
    def test_the_table_validator_catches_it(self):
        """This is the whole point — the gate that actually runs must see it."""
        issues = validate_annotation_table(table("x" * 1182))
        assert any(i.field == "Comments" and i.severity == ERROR for i in issues)

    def test_a_normal_comment_produces_no_comment_issue(self):
        issues = validate_annotation_table(table("A perfectly ordinary provenance note."))
        assert not [i for i in issues if i.field == "Comments"]

    def test_a_sheet_without_a_comments_column_is_unaffected(self):
        df = table("x")
        df = df.drop(columns=["Comments"])
        assert not [i for i in validate_annotation_table(df) if i.field == "Comments"]
