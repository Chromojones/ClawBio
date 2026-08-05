"""Tests for paper_metadata_enrich."""

from __future__ import annotations

import pandas as pd

from lib.flow_annotate import ANNOTATION_COLUMNS
from lib.paper_metadata_enrich import (
    enrich_annotation_from_paper,
    extract_antibodies_from_text,
    is_generic_purification_agent,
)

TIA_METHODS = (
    "For iCLIP, TIA1 or TIAL1 were immunoprecipitated with protein G Dynabeads "
    "(Invitrogen) conjugated to goat-anti TIA1 (Santa Cruz, C-20) or "
    "goat-anti TIAL1 (Santa Cruz, C-18) antibody."
)


# GSE215250 / PMID 38495826: the Key Resources table lists TWO PARP13 antibodies.
# Only the Methods sentence naming the assay identifies the one used for eCLIP.
PARP13_METHODS = (
    "Western blotting was performed with rabbit anti-PARP13 antibody "
    "(ProteinTech, 16820-1-AP) at 1:1,000 dilution. "
    "eCLIP was performed as previously published using anti-PARP13 antibody "
    "(Thermofisher Scientific, PA5-31650)."
)


def test_extract_antibodies_from_methods():
    agents = extract_antibodies_from_text(TIA_METHODS)
    assert agents["TIA1"] == "Goat Anti-TIA1 (Santa Cruz C-20)"
    assert agents["TIAL1"] == "Goat Anti-TIAL1 (Santa Cruz C-18)"


def test_extract_antibodies_beyond_the_legacy_three_targets():
    """PARP13 is not TIA1/TIAL1/TIAR — it must still resolve."""
    agents = extract_antibodies_from_text(PARP13_METHODS)
    assert "PARP13" in agents


def test_assay_sentence_wins_over_western_blot_sentence():
    """The eCLIP antibody, not the first one mentioned in the paper."""
    agents = extract_antibodies_from_text(PARP13_METHODS)
    assert agents["PARP13"] == "Anti-PARP13 (Thermofisher Scientific PA5-31650)"
    assert "16820-1-AP" not in agents["PARP13"]


def test_is_generic_purification_agent():
    assert is_generic_purification_agent("anti-TIA1 antibody")
    assert not is_generic_purification_agent("Goat Anti-TIA1 (Santa Cruz C-20)")


def test_generic_detection_catches_self_synthesized_values():
    """Strings this skill itself used to emit must be flagged, not accepted."""
    assert is_generic_purification_agent("CPSF5 antibody")
    assert is_generic_purification_agent("V5-antibody")


def test_iclap_literal_is_not_generic():
    """Regression: the check used to search the agent value for the word 'iclap'."""
    assert not is_generic_purification_agent("Strep/His affinity tag purification")
    assert not is_generic_purification_agent("no antibody")


def test_enrich_annotation_from_paper_local_text():
    row = {col: "" for col in ANNOTATION_COLUMNS}
    row.update(
        {
            "Sample Name": "TIA1_Hs_HeLa_TGNNN_ERR1",
            "Protein (Purification Target)": "TIA1",
            "Purification Agent": "anti-TIA1 antibody",
            "Experimental Method": "iCLIP",
            "PI": "König",
            "PubMed ID": "20544596",
        }
    )
    df = pd.DataFrame([row], columns=ANNOTATION_COLUMNS)
    enriched, paper, warnings = enrich_annotation_from_paper(
        df, "21048981", paper_text=TIA_METHODS
    )
    assert enriched.iloc[0]["Purification Agent"] == "Goat Anti-TIA1 (Santa Cruz C-20)"
    if paper.first_author:
        assert enriched.iloc[0]["Scientist"] == paper.first_author
    if paper.last_author:
        assert enriched.iloc[0]["PI"] == paper.last_author
    assert enriched.iloc[0]["PubMed ID"] == "21048981"
    assert not any(w.field == "Purification Agent" for w in warnings)
