"""FLAG-HA-HIS is one tag, not three, and not a mutation followed by a tag.

GSE131210 expresses 41 of its 50 samples as "FLAG-HA-HIS tagged ORF" — the FHH cassette, a
single triple-epitope tag. The annotation grammar is `mutation-tag`, tag last, hyphen
separated, with composite tags listed explicitly in `TAGS` (this is why `3xFLAG-HBH` is there
as one entry rather than being assembled).

Without an entry, `nFLAG-HA-HIS` is rejected as bad grammar. The two repairs that grammar
error invites are both wrong:

- `nFLAG` or `nHA` alone — records a single-epitope construct that was not what was expressed.
- letting `FLAG-HA` parse as a mutation named `FLAG` on a tag `HA` — the regex would happily
  read `dNTR-nMYC`-shaped input that way, silently turning an epitope into a protein
  alteration.

The PCBP1 cancer-mutation samples exercise both halves at once: target `PCBP1`, mutation
`100Q`, tag `nFLAG-HA-HIS`, which must parse as exactly that and nothing else.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import ERROR, TAGS, _TAG_RE, validate_target_and_annotation  # noqa: E402


class TestTheVocabulary:
    def test_fhh_is_a_known_tag(self):
        assert "FLAG-HA-HIS" in TAGS

    def test_the_existing_composite_is_untouched(self):
        assert "3xFLAG-HBH" in TAGS

    def test_it_is_listed_before_its_own_prefixes(self):
        """The alternation is longest-first; if `FLAG` came first, `FLAG-HA-HIS` would parse
        as tag `FLAG` with trailing junk and be rejected."""
        assert TAGS.index("FLAG-HA-HIS") < TAGS.index("FLAG")
        assert TAGS.index("FLAG-HA-HIS") < TAGS.index("HA")
        assert TAGS.index("FLAG-HA-HIS") < TAGS.index("HIS")


class TestItParsesAsOneTag:
    def test_n_terminal(self):
        m = _TAG_RE.match("nFLAG-HA-HIS")
        assert m and m.group("tag") == "nFLAG-HA-HIS"
        assert m.group("mutation") is None

    def test_c_terminal(self):
        m = _TAG_RE.match("cFLAG-HA-HIS")
        assert m and m.group("tag") == "cFLAG-HA-HIS"

    def test_it_is_not_read_as_a_mutation_plus_tag(self):
        """`FLAG` must not become a protein alteration applied to an `HA` tag."""
        assert _TAG_RE.match("nFLAG-HA-HIS").group("mutation") is None


class TestTheGse131210Rows:
    def test_a_tagged_row_validates(self):
        checks = validate_target_and_annotation(
            target="hnRNPD", annotation="nFLAG-HA-HIS", agent="Anti-HA",
            sample_name="hnRNPD_HEK293T_Hs_rep1_SRX5830818")
        assert [c for c in checks if c.severity == ERROR] == []

    def test_a_pcbp1_mutant_row_keeps_mutation_and_tag_separate(self):
        m = _TAG_RE.match("100Q-nFLAG-HA-HIS")
        assert m and m.group("mutation") == "100Q" and m.group("tag") == "nFLAG-HA-HIS"

    def test_the_pcbp1_mutant_row_validates(self):
        checks = validate_target_and_annotation(
            target="PCBP1", annotation="100Q-nFLAG-HA-HIS", agent="Anti-HA",
            sample_name="PCBP1_HCT116_Hs_100Q_rep1_SRX5830826")
        assert [c for c in checks if c.severity == ERROR] == []

    def test_an_orientationless_tag_is_still_refused(self):
        """`FLAG-HA-HIS` with no leading n/c states a construct nobody built."""
        assert _TAG_RE.match("FLAG-HA-HIS") is None
