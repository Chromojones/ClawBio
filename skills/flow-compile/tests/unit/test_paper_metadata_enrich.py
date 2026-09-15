"""Tests for paper_metadata_enrich."""

from __future__ import annotations

import pandas as pd

from lib.flow_annotate import ANNOTATION_COLUMNS
from lib.paper_metadata_enrich import (
    collect_annotation_field_warnings,
    enrich_annotation_from_paper,
    extract_antibodies_from_text,
    is_generic_purification_agent,
)

TIA_METHODS = (
    "For iCLIP, TIA1 or TIAL1 were immunoprecipitated with protein G Dynabeads "
    "(Invitrogen) conjugated to goat-anti TIA1 (Santa Cruz, C-20) or "
    "goat-anti TIAL1 (Santa Cruz, C-18) antibody."
)

# GSE149561 / PMID 33030396: the study names its target SYNCRIP; the Methods name the
# antibody by the alias hnRNP Q.
SYNCRIP_METHODS = (
    "SYNCRIP protein was immunoprecipitated with 10 ug of mouse anti-hnRNPQ antibody "
    "(clone 18E4, Sigma) coupled to 50 ul of Dynabeads Protein G for 2 hours at 4C. "
    "As a control for unspecific binding, mAb IgG1 Isotype (#5415, Cell signalling) was applied."
)


# GSE215250 / PMID 38495826: the Key Resources table lists TWO PARP13 antibodies.
# Only the Methods sentence naming the assay identifies the one used for eCLIP.
PARP13_METHODS = (
    "Western blotting was performed with rabbit anti-PARP13 antibody "
    "(ProteinTech, 16820-1-AP) at 1:1,000 dilution. "
    "eCLIP was performed as previously published using anti-PARP13 antibody "
    "(Thermofisher Scientific, PA5-31650)."
)


class TestFetchFailureFallsBack:
    """A failed or timed-out fetch leaves 04 with the PubMed authors and any supplied excerpt."""

    def _fail(self, monkeypatch, exc):
        import lib.paper_metadata_enrich as pme

        def boom(*a, **k):
            raise exc

        monkeypatch.setattr(pme, "_http_get", boom)
        return pme

    def test_a_404_from_the_fulltext_endpoint_is_swallowed(self, monkeypatch):
        """Fixture: PMC8354602 (GSE149561), absent from Europe PMC's full-text set."""
        pme = self._fail(monkeypatch, RuntimeError("HTTP 404 for .../PMC8354602/fullTextXML"))
        assert pme.fetch_pmc_methods_text("PMC8354602") == ""

    def test_a_timeout_is_swallowed_by_every_fetch(self, monkeypatch):
        pme = self._fail(monkeypatch, TimeoutError("The read operation timed out"))
        assert pme.fetch_pmc_methods_text("PMC8354602") == ""
        assert pme.fetch_pubmed_record("33030396") == ("", [])
        assert pme._pmcid_for_pmid("33030396") == ""

    def test_load_paper_metadata_still_returns_when_fulltext_404s(self, monkeypatch):
        pme = self._fail(monkeypatch, RuntimeError("HTTP 404 for .../PMC8354602/fullTextXML"))
        monkeypatch.setattr(pme, "fetch_pubmed_record", lambda pmid: (
            "The cytoplasmic SYNCRIP mRNA interactome of mammalian neurons",
            ["Sharof Khudayberdiev", "Gerhard Schratt"],
        ))
        monkeypatch.setattr(pme, "_pmcid_for_pmid", lambda pmid: "PMC8354602")
        paper = pme.load_paper_metadata("33030396")
        assert paper.first_author == "Sharof Khudayberdiev"
        assert paper.last_author == "Gerhard Schratt"


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


def test_antibody_alias_resolves_to_the_studys_canonical_target():
    """hnRNP Q is SYNCRIP: the antibody is keyed by the gene symbol the target column uses."""
    agents = extract_antibodies_from_text(SYNCRIP_METHODS)
    assert "SYNCRIP" in agents
    assert "HNRNPQ" not in agents
    assert agents["SYNCRIP"] == "Mouse Anti-SYNCRIP (clone 18E4 Sigma)"


def test_is_generic_purification_agent():
    assert is_generic_purification_agent("anti-TIA1 antibody")
    assert not is_generic_purification_agent("Goat Anti-TIA1 (Santa Cruz C-20)")


def test_generic_detection_catches_self_synthesized_values():
    """Generic agent strings are flagged, not accepted."""
    assert is_generic_purification_agent("CPSF5 antibody")
    assert is_generic_purification_agent("V5-antibody")


def test_iclap_literal_is_not_generic():
    """An agent value containing `iclap` is not generic by that alone."""
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
        df, "21048981", paper_text=TIA_METHODS, offline=True
    )
    assert enriched.iloc[0]["Purification Agent"] == "Goat Anti-TIA1 (Santa Cruz C-20)"
    if paper.first_author:
        assert enriched.iloc[0]["Scientist"] == paper.first_author
    if paper.last_author:
        assert enriched.iloc[0]["PI"] == paper.last_author
    assert enriched.iloc[0]["PubMed ID"] == "21048981"
    assert not any(w.field == "Purification Agent" for w in warnings)


class TestControlAgents:
    """A target in `metadata_validate.CONTROL_TARGETS` carries an empty agent, never the literal
    `no antibody`; every other target keeps its antibody.
    """

    def _row(self, target, agent=""):
        row = {col: "" for col in ANNOTATION_COLUMNS}
        row.update({
            "Sample Name": f"{target}_Rn_x_Rep1_SRR1",
            "Protein (Purification Target)": target,
            "Purification Agent": agent,
            "Experimental Method": "iCLIP",
            "PubMed ID": "33030396",
        })
        return pd.DataFrame([row], columns=ANNOTATION_COLUMNS)

    def _enrich(self, df):
        return enrich_annotation_from_paper(df, "33030396", paper_text="", offline=True)

    def test_an_igg_row_resolves_to_empty(self):
        """GSE149561's IgG rows carry GEO's isotype reagent; the gate refuses any agent on IgG."""
        enriched, _, warnings = self._enrich(
            self._row("IgG", "mAb IgG1 Isotype (#5415, Cell signaling)"))
        assert enriched.iloc[0]["Purification Agent"] == ""
        assert not any(w.field == "Purification Agent" for w in warnings)

    def test_a_gfp_row_keeps_its_antibody(self):
        """A GFP target is an anti-GFP pulldown, not a no-antibody control."""
        enriched, _, _ = self._enrich(self._row("GFP", "Mouse Anti-GFP (Roche 11814460001)"))
        assert enriched.iloc[0]["Purification Agent"] == "Mouse Anti-GFP (Roche 11814460001)"

    def test_an_empty_agent_on_a_control_row_is_not_flagged(self):
        for target in ("IgG", "SMInput", "noAbCtrl"):
            warnings = collect_annotation_field_warnings(self._row(target))
            assert not any(w.field == "Purification Agent" for w in warnings), target

    def test_an_empty_agent_on_an_ip_or_gfp_row_is_flagged(self):
        for target in ("SYNCRIP", "GFP"):
            warnings = collect_annotation_field_warnings(self._row(target))
            assert any(w.field == "Purification Agent" for w in warnings), target


class TestOfflineMeansOffline:
    """`00_setup --offline` reaches the enrichment: no Europe PMC fetch."""

    def _explode(self, monkeypatch):
        import lib.paper_metadata_enrich as pme

        def boom(*a, **k):
            raise AssertionError("offline run attempted a network fetch")

        monkeypatch.setattr(pme, "_http_get", boom)

    def test_load_paper_metadata_makes_no_call_when_offline(self, monkeypatch):
        from lib.paper_metadata_enrich import load_paper_metadata

        self._explode(monkeypatch)
        paper = load_paper_metadata("21048981", paper_text=TIA_METHODS, offline=True)
        assert paper.pmid == "21048981"
        assert TIA_METHODS.strip()[:20] in paper.methods_text

    def test_the_supplied_excerpt_still_drives_enrichment(self, monkeypatch):
        """Offline must not mean unenriched: the attached Methods still resolve the agent."""
        from lib.paper_metadata_enrich import enrich_annotation_from_paper

        self._explode(monkeypatch)
        row = {col: "" for col in ANNOTATION_COLUMNS}
        row.update({
            "Sample Name": "TIA1_Hs_HeLa_TGNNN_ERR1",
            "Protein (Purification Target)": "TIA1",
            "Purification Agent": "anti-TIA1 antibody",
            "Experimental Method": "iCLIP",
        })
        df = pd.DataFrame([row], columns=ANNOTATION_COLUMNS)
        enriched, _, _ = enrich_annotation_from_paper(
            df, "21048981", paper_text=TIA_METHODS, offline=True)
        assert enriched.iloc[0]["Purification Agent"] == "Goat Anti-TIA1 (Santa Cruz C-20)"
