"""A download that returns HTTP 200 may still not be the file.

Flow serves single files from ``GET {FLOW_API_URL}/downloads/<data_id>/<filename>``. Three
things about that URL are easy to get wrong, and none of them announce themselves:

1. **It is a Data id, not a download-job id**, despite the ``/downloads/`` prefix. The bulk
   flow (``POST /downloads/...``) uses a job id and a different pattern entirely.
2. **The trailing segment must equal ``data.filename`` exactly.** A mismatch is a 404.
3. **It lives under ``/api``.** Probing ``/api/data/<id>/download``, ``/raw``, ``/link``,
   ``/signed``, ``/blob`` and ``/files/<id>`` all return 404, and so does
   ``/api/downloads/data/<id>``. Nothing in those failures hints at the real shape.

The dangerous part is what happens when the host or path is wrong rather than absent. Asking
``https://app.flow.bio/downloads/<id>/<name>`` — the same path without ``/api`` — returns
**HTTP 206 with the single-page-app's HTML shell**::

    <!doctype html><html lang="en"><head><meta charset="utf-8"/>...<title>Flow</title>

A 2xx, a plausible byte count, and a body that is a web page. Written straight to
``ELAVL1_K562_1.genome.xl.bed`` that is a 401-byte "BED file" that every downstream tool will
read as malformed input, or worse, skip as a comment-free header. The real file is 348 MB.

Refusals compound it: this endpoint returns a **bare 404 with no JSON body**, where the rest of
the API returns ``{"error": ...}``. So the usual "did the response parse as JSON?" check
inverts — here JSON means something went wrong.

The defence cannot be the status code. It has to be the bytes: a crosslink BED begins with a
chromosome field and tab-separated columns, never with ``<`` or ``{``.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.data_download import (  # noqa: E402
    download_url,
    looks_like_payload,
    check_download,
)


class TestTheUrl:
    def test_it_is_built_from_data_id_and_exact_filename(self):
        assert download_url("657562493133188868", "ELAVL1_K562_1.genome.xl.bed") == (
            "https://app.flow.bio/api/downloads/657562493133188868/"
            "ELAVL1_K562_1.genome.xl.bed"
        )

    def test_it_sits_under_api(self):
        """Without /api the same path serves the SPA shell with a 2xx."""
        assert "/api/downloads/" in download_url("1", "x.bed")

    def test_the_base_can_be_overridden(self):
        url = download_url("1", "x.bed", base="https://staging.flow.bio/api")
        assert url.startswith("https://staging.flow.bio/api/downloads/")

    def test_a_filename_is_required(self):
        """The trailing segment is part of the route, not decoration — omitting it 404s."""
        try:
            download_url("1", "")
        except ValueError:
            return
        raise AssertionError("empty filename must be refused")


class TestTheBytes:
    def test_a_crosslink_bed_is_accepted(self):
        assert looks_like_payload(b"1\t15934\t15935\t.\t1\t-\n1\t15976\t15977\t.\t1\t-\n")

    def test_the_spa_shell_is_refused(self):
        """Verbatim first bytes of the wrong-path response, which arrived as HTTP 206."""
        assert not looks_like_payload(
            b'<!doctype html><html lang="en"><head><meta charset="utf-8"/>')

    def test_a_json_error_is_refused(self):
        """This endpoint 404s with an empty body; a JSON body means a different handler."""
        assert not looks_like_payload(b'{"error": {"detail": "Not found"}}')

    def test_an_empty_body_is_refused(self):
        assert not looks_like_payload(b"")

    def test_leading_whitespace_does_not_smuggle_html_through(self):
        assert not looks_like_payload(b"\n   <!doctype html>")

    def test_gzip_magic_is_accepted(self):
        """Some crosslink products are .bed.gz / .bedgraph.gz."""
        assert looks_like_payload(b"\x1f\x8b\x08\x00")


class TestTheVerdict:
    def test_a_good_download_passes(self):
        result = check_download(status=200, head=b"1\t15934\t15935\t.\t1\t-\n",
                                size=347855332, expected_size=347855332)
        assert result.ok is True

    def test_a_200_carrying_html_fails_and_says_why(self):
        result = check_download(status=206, head=b"<!doctype html><html", size=401,
                                expected_size=347855332)
        assert result.ok is False
        assert "html" in result.reason.lower()

    def test_a_size_mismatch_fails(self):
        """A truncated transfer is valid BED for as far as it goes."""
        result = check_download(status=200, head=b"1\t15934\t15935\t.\t1\t-\n",
                                size=1_000_000, expected_size=347855332)
        assert result.ok is False
        assert "size" in result.reason.lower()

    def test_a_404_fails_even_with_an_empty_body(self):
        result = check_download(status=404, head=b"", size=0, expected_size=100)
        assert result.ok is False

    def test_expected_size_is_optional(self):
        result = check_download(status=200, head=b"1\t1\t2\t.\t1\t+\n", size=42)
        assert result.ok is True
