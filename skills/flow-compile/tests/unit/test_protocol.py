"""One place that knows what a CLIP protocol is called and what follows from it.

`is_eclip_method` existed twice with two sources of truth — `pipeline_params` read a module
constant, `flow_annotate` inlined the same set as a literal. Two definitions of "is this
eCLIP?" is one more than a codebase can keep honest, and this parameter decides which mate
carries the crosslink.

Protocol *detection* also lived in `flow_annotate._match_method` while the question "is this
annotation eCLIP?" lived in `flow_compile._annotation_is_eclip` — orchestrator logic that
belongs with the other protocol knowledge.

The ordering constraint is load-bearing and easy to lose: `PAR-iCLIP` must be tested before
both `PAR-CLIP` and `iCLIP`, because `par[\\s-]?clip` cannot match "PAR-iCLIP" (the next token
is `iclip`, not `clip`) and the bare `iclip` pattern then matches the tail of that same word.
GSE207656 read as `iCLIP` for months for exactly this reason.

Story: FAILURES.md#protocol-detection
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.protocol import (  # noqa: E402
    ECLIP_FAMILY,
    detect_method,
    is_eclip_method,
)


class TestOneDefinitionOfEclip:
    def test_the_family(self):
        assert ECLIP_FAMILY == frozenset({"eclip", "seclip"})

    def test_eclip_and_seclip(self):
        assert is_eclip_method("eCLIP")
        assert is_eclip_method("seCLIP")

    def test_case_and_whitespace(self):
        assert is_eclip_method("  ECLIP ")

    def test_par_iclip_is_not_eclip_family(self):
        """4sU labelling with iCLIP chemistry; encode_eclip does not apply."""
        assert not is_eclip_method("PAR-iCLIP")

    def test_iclip_is_not(self):
        assert not is_eclip_method("iCLIP")

    def test_empty_is_not(self):
        assert not is_eclip_method("") and not is_eclip_method(None)


class TestDetectionOrdering:
    def test_par_iclip_beats_both_par_clip_and_iclip(self):
        """GSE207656's title is 'PAR-iCLIP MCMV infection'."""
        assert detect_method("", "PAR-iCLIP MCMV infection") == "PAR-iCLIP"

    def test_par_iclip_in_protocol_prose(self):
        assert detect_method("PAR-iCLIP was performed using 4-thiouridine") == "PAR-iCLIP"

    def test_classic_par_clip_still_resolves(self):
        assert detect_method("", "PAR-CLIP of QKI") == "PAR-CLIP"

    def test_plain_iclip_still_resolves(self):
        assert detect_method("", "iCLIP of LARP6") == "iCLIP"

    def test_the_other_flavours(self):
        assert detect_method("", "irCLIP of ELAVL1") == "irCLIP"
        assert detect_method("", "eCLIP of PARP13") == "eCLIP"
        assert detect_method("", "seCLIP") == "seCLIP"

    def test_title_beats_protocol_prose(self):
        """Extract protocols routinely cite OTHER protocols ('as described for eCLIP')."""
        assert detect_method("performed as described for eCLIP", "iCLIP of LARP6") == "iCLIP"

    def test_unknown_falls_back_to_iclip(self):
        assert detect_method("some assay", "") == "iCLIP"


class TestAnnotationLevel:
    def test_an_eclip_annotation_is_recognised(self):
        from lib.protocol import annotation_is_eclip
        assert annotation_is_eclip([{"Experimental Method": "eCLIP"}])

    def test_a_mixed_annotation_is_eclip_if_any_row_is(self):
        from lib.protocol import annotation_is_eclip
        assert annotation_is_eclip([{"Experimental Method": "iCLIP"},
                                    {"Experimental Method": "seCLIP"}])

    def test_an_iclip_annotation_is_not(self):
        from lib.protocol import annotation_is_eclip
        assert not annotation_is_eclip([{"Experimental Method": "iCLIP"}])

    def test_an_empty_annotation_is_not(self):
        from lib.protocol import annotation_is_eclip
        assert not annotation_is_eclip([])
