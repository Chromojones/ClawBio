"""Check the data is public BEFORE doing any metadata work.

AUTS2 (PMID 41278797) is an ideal candidate on paper: eCLIP of a genuinely new protein in
human neural progenitors, exactly the brain context we are short of. Its Data Availability
statement names three GEO accessions, all of which read as ordinary published data.

Every one of them is private, **scheduled for release on 07 Aug 2029**. That cost a full
literature dig — abstract, Europe PMC, PMC efetch, bioRxiv full text, methods extraction —
before the first line of metadata could have been written.

One HTTP request, made first, would have ended it. The check is cheap, decisive, and belongs
in front of the pipeline rather than in the middle of it.

The parsing itself has one trap worth pinning: GEO's `form=text` endpoint returns SOFT text
for a public accession and an **HTML page** for a private one, so "did I get SOFT back" is
the actual signal. Sniffing for the word "private" alone would misread a public series whose
summary happens to discuss private data.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.accession_availability import (  # noqa: E402
    Availability,
    parse_geo_response,
)

# GEO `form=text&view=brief` for a released series, trimmed.
PUBLIC_SOFT = """^SERIES = GSE159997
!Series_title = Unbiased identification of CSDE1-regulated targets [i-CLIP]
!Series_pubmed_id = 35021076
!Series_sample_id = GSM4852294
!Series_sample_id = GSM4852295
!Series_relation = SRA: https://www.ncbi.nlm.nih.gov/sra?term=SRP288389
"""

# The same endpoint for an embargoed series returns a full HTML page. Verbatim sentence.
PRIVATE_HTML = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<HTML><HEAD><title>GEO Accession viewer</title></HEAD><BODY>
GEO accession: Series <b>GSE304933</b>
Accession "GSE304933" is currently private and is scheduled to be released on Aug 07, 2029.
If you are the owner of this accession you must login to view this accession.
If you are a reviewer, enter secure token here:
</BODY></HTML>"""

WITHDRAWN_HTML = """<HTML><BODY>
Accession "GSE999999" could not be found in the GEO database.
</BODY></HTML>"""


class TestAPublicSeries:
    def test_soft_text_reads_as_public(self):
        result = parse_geo_response("GSE159997", PUBLIC_SOFT)
        assert result.public is True
        assert result.sample_count == 2
        assert result.release_date == ""

    def test_the_pubmed_id_is_picked_up_for_free(self):
        """It is on the same response, and the upload needs it anyway."""
        assert parse_geo_response("GSE159997", PUBLIC_SOFT).pubmed == "35021076"

    def test_a_public_series_is_not_tripped_by_the_word_private(self):
        """A summary discussing 'private' data must not be read as an embargo.

        The signal is "did GEO return SOFT", not "does the page contain a word".
        """
        soft = PUBLIC_SOFT + "!Series_summary = Data from a private patient cohort.\n"
        assert parse_geo_response("GSE159997", soft).public is True


class TestAnEmbargoedSeries:
    """The AUTS2 regression, verbatim."""

    def test_private_html_reads_as_not_public(self):
        result = parse_geo_response("GSE304933", PRIVATE_HTML)
        assert result.public is False
        assert result.sample_count == 0

    def test_the_release_date_is_reported_because_it_decides_what_to_do(self):
        """Weeks away means wait; 2029 means ask the authors or drop the study."""
        assert parse_geo_response("GSE304933", PRIVATE_HTML).release_date == "Aug 07, 2029"

    def test_the_reason_names_the_embargo_not_a_generic_failure(self):
        assert "private" in parse_geo_response("GSE304933", PRIVATE_HTML).reason.lower()

    def test_a_missing_accession_is_distinguished_from_an_embargoed_one(self):
        """Different problems: one is a typo, the other is a wait or an email."""
        result = parse_geo_response("GSE999999", WITHDRAWN_HTML)
        assert result.public is False
        assert result.release_date == ""
        assert "not found" in result.reason.lower()


class TestAnEmptyOrTruncatedResponse:
    def test_an_empty_body_is_not_silently_treated_as_public(self):
        """A failed fetch became an empty row once already and produced phantom findings."""
        result = parse_geo_response("GSE159997", "")
        assert result.public is False
        assert "empty" in result.reason.lower()

    def test_soft_text_with_no_samples_is_not_public(self):
        """A series header with zero `!Series_sample_id` lines has nothing to import."""
        result = parse_geo_response("GSE1", "^SERIES = GSE1\n!Series_title = x\n")
        assert result.public is False
        assert "no samples" in result.reason.lower()


class TestTheMessage:
    def test_an_embargo_message_names_the_date_and_says_to_stop(self):
        text = Availability(
            accession="GSE304933", public=False,
            release_date="Aug 07, 2029", reason="private until Aug 07, 2029",
        ).describe()
        assert "GSE304933" in text and "Aug 07, 2029" in text

    def test_a_public_message_states_the_sample_count(self):
        text = Availability(accession="GSE159997", public=True, sample_count=18).describe()
        assert "18" in text and "GSE159997" in text
