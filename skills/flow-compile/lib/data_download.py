"""Pull a single file off Flow, and prove that what arrived is the file.

Flow serves single files from ``GET {FLOW_API_URL}/downloads/<data_id>/<filename>``. Three
properties of that route are easy to get wrong and none of them announce themselves:

1. The id is a **Data id**, not a download-job id, despite the ``/downloads/`` prefix — the
   bulk flow (``POST /downloads/...``) uses a job id and a different pattern.
2. The trailing segment must equal ``data.filename`` **exactly**; a mismatch 404s.
3. It lives under ``/api``. Probing ``/api/data/<id>/download``, ``/raw``, ``/link``,
   ``/signed``, ``/blob``, ``/files/<id>`` and ``/api/downloads/data/<id>`` all 404 with
   nothing to suggest the real shape.

The failure that matters is not the 404. Requesting the same path **without** ``/api`` —
``https://app.flow.bio/downloads/<id>/<name>`` — returns **HTTP 206 carrying the single-page
app's HTML shell**::

    <!doctype html><html lang="en"><head><meta charset="utf-8"/>...<title>Flow</title>

A 2xx, a plausible byte count, and a body that is a web page. Written to
``ELAVL1_K562_1.genome.xl.bed`` that is a 401-byte "BED file"; the real one is 348 MB. Every
downstream tool then reads malformed input, or silently finds no crosslinks.

Refusals invert the usual test too: this endpoint returns a **bare 404 with no JSON body**
where the rest of the API returns ``{"error": ...}``. Here a JSON body is itself a symptom.

So verification is on the bytes and the size, never on the status code alone.

Pure — the caller performs the transfer.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BASE = "https://app.flow.bio/api"

#: First bytes that prove the response is NOT the payload: an HTML page or a JSON error.
_NOT_PAYLOAD_PREFIXES = (b"<", b"{")

#: gzip magic — several crosslink products are served compressed.
_GZIP_MAGIC = b"\x1f\x8b"


def download_url(data_id: str, filename: str, *, base: str = DEFAULT_BASE) -> str:
    """The single-file download URL.

    ``filename`` is part of the route, not decoration: it must equal ``data.filename``
    exactly or the endpoint 404s.
    """
    filename = str(filename or "").strip()
    if not filename:
        raise ValueError(
            "filename is required — it is a path segment of the download route and must "
            "equal data.filename exactly (take it from GET /api/data/<id>)"
        )
    return f"{base.rstrip('/')}/downloads/{data_id}/{filename}"


def looks_like_payload(head: bytes) -> bool:
    """Do these first bytes look like a real file rather than a page or an error?

    The SPA shell arrives with a 2xx, so the status code cannot answer this.
    """
    if not head:
        return False
    if head.startswith(_GZIP_MAGIC):
        return True
    stripped = head.lstrip()
    if not stripped:
        return False
    return not stripped.startswith(_NOT_PAYLOAD_PREFIXES)


@dataclass
class DownloadCheck:
    ok: bool
    reason: str = ""


def check_download(
    *, status: int, head: bytes, size: int, expected_size: int | None = None
) -> DownloadCheck:
    """Did this transfer actually deliver the file?"""
    if status >= 400:
        return DownloadCheck(
            False,
            f"HTTP {status}. This endpoint returns a bare 404 with no JSON body — the id may "
            f"be wrong, the filename may not match data.filename exactly, the file may not be "
            f"ready, or the data may not be readable by this caller.",
        )
    if not looks_like_payload(head):
        stripped = head.lstrip()[:40]
        if stripped.startswith(b"<"):
            return DownloadCheck(
                False,
                f"HTTP {status} but the body is HTML, not the file — this is the single-page "
                f"app shell, which is what the same path WITHOUT /api serves. Rebuild the URL "
                f"with download_url(). Got: {stripped!r}",
            )
        return DownloadCheck(
            False,
            f"HTTP {status} but the body is not the file (starts {stripped!r}). A JSON body "
            f"here means a different handler answered.",
        )
    if expected_size is not None and size != expected_size:
        return DownloadCheck(
            False,
            f"size mismatch: got {size:,} bytes, data record says {expected_size:,}. A "
            f"truncated transfer is still valid for as far as it goes and will not error "
            f"downstream — re-fetch rather than use it.",
        )
    return DownloadCheck(True)
