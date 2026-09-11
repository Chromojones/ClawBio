"""Remote FASTQ header preview for the SRA-direct line, used by `101_preview`.

Fetches a few records per run from ENA, which renders deflines as
`@<run>.<n> <original spot name>` — the form Flow itself fetches, so the preview sees the study
as the import will. `fastq-dump --origfmt` is the fallback when ENA does not serve a run.

Story: FAILURES.md#defline-provenance
"""

from __future__ import annotations

import gzip
import subprocess
import urllib.request
import zlib

from lib.fastq_headers import (
    RBC_TAG,
    HeaderInspection,
    inspect_header_lines,
)

ENA_FILEREPORT = (
    "https://www.ebi.ac.uk/ena/portal/api/filereport"
    "?accession={accession}&result=read_run&fields=fastq_ftp&format=tsv"
)

#: Leading bytes of each .gz to pull. ~500 KB decompresses to far more than a few reads.
DEFAULT_RANGE_BYTES = 500_000
DEFAULT_READS = 4


def parse_ena_fastq_urls(tsv: str) -> list[str]:
    """FASTQ URLs from an ENA filereport TSV, found by content: paired runs join both mates in one
    semicolon-separated field.
    """
    urls: list[str] = []
    for line in (tsv or "").splitlines()[1:]:
        for field in line.split("\t"):
            if "ftp." not in field or ".fastq.gz" not in field:
                continue
            for part in field.split(";"):
                part = part.strip()
                if part:
                    urls.append(part if part.startswith("http") else f"https://{part}")
            break
    return urls


def _http_get(url: str, *, byte_range: int | None = None, timeout: int = 60) -> bytes:
    headers = {"User-Agent": "flow-compile/1.0"}
    if byte_range:
        headers["Range"] = f"bytes=0-{byte_range}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _decompress_partial(blob: bytes) -> str:
    """Inflate a truncated gzip stream, keeping whatever decoded before it ran out."""
    try:
        return gzip.decompress(blob).decode("utf-8", errors="replace")
    except (OSError, EOFError, zlib.error):
        pass
    decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)
    try:
        return decompressor.decompress(blob).decode("utf-8", errors="replace")
    except zlib.error:
        return ""


def _records_from_text(text: str, n_reads: int) -> list[str]:
    """First ``n_reads`` complete 4-line FASTQ records as a flat line list."""
    lines = text.splitlines()
    usable = (len(lines) // 4) * 4
    return lines[: min(usable, n_reads * 4)]


def fetch_ena_fastq_urls(accession: str) -> list[str]:
    try:
        payload = _http_get(ENA_FILEREPORT.format(accession=accession)).decode()
    except Exception:  # noqa: BLE001 - offline / unknown accession is not fatal
        return []
    return parse_ena_fastq_urls(payload)


def preview_run(
    run_accession: str,
    *,
    n_reads: int = DEFAULT_READS,
    range_bytes: int = DEFAULT_RANGE_BYTES,
    mate: int = 1,
) -> tuple[list[str], str]:
    """Return (records, source) for one run. ``source`` is 'ena' or 'fastq-dump'."""
    urls = fetch_ena_fastq_urls(run_accession)
    if urls:
        index = min(max(mate, 1) - 1, len(urls) - 1)
        try:
            blob = _http_get(urls[index], byte_range=range_bytes)
            records = _records_from_text(_decompress_partial(blob), n_reads)
            if records:
                return records, "ena"
        except Exception:  # noqa: BLE001 - fall through to the SRA path
            pass

    try:
        proc = subprocess.run(
            ["fastq-dump", "-X", str(n_reads), "-Z", "--origfmt", run_accession],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        return _records_from_text(proc.stdout, n_reads), "fastq-dump"
    except (OSError, subprocess.SubprocessError):
        return [], "unavailable"


def umi_is_stranded_in_comment(header: str, *, source: str = "ena") -> bool:
    """True when the `rbc:` UMI will sit in the comment field once Flow fetches the run.

    Aligners drop the comment, so the UMI never reaches the BAM and deduplication fails. A
    `fastq-dump --origfmt` header has no comment field; its name becomes the comment once the
    accession is prefixed, so `source` decides how it is read.

    Story: FAILURES.md#defline-provenance
    """
    body = str(header or "").lstrip("@")
    name, sep, comment = body.partition(" ")
    if not sep:
        return source == "fastq-dump" and RBC_TAG.search(name) is not None
    return RBC_TAG.search(comment) is not None and RBC_TAG.search(name) is None


def inspection_from_header_records(
    records_by_run: dict[str, list[str]],
    sources: dict[str, str] | None = None,
) -> HeaderInspection:
    """A HeaderInspection from fetched records, using the same `inspect_header_lines` as the local
    path. `sources` names each run's fetch source, which the comment verdict depends on.
    """
    flat: list[str] = []
    umi_in_comment = False
    for run, records in records_by_run.items():
        flat.extend(records)
        source = (sources or {}).get(run, "ena")
        umi_in_comment = umi_in_comment or any(
            umi_is_stranded_in_comment(h, source=source)
            for h in records if str(h).startswith("@")
        )

    has_rbc, has_underscore = inspect_header_lines(flat)
    if umi_in_comment:
        notes = (
            "UMI tag is in the header COMMENT (after the first space), not the read name. "
            "Aligners drop the comment, so the UMI will not reach the BAM and dedup will "
            "fail — SRA-direct import cannot be used. Download locally and fold the comment "
            "into the read name (removespace.py) before uploading."
        )
    elif has_rbc:
        notes = "Headers contain :rbc: — barcode already in read name."
    elif has_underscore:
        notes = "Headers contain underscore-suffixed barcode (not rbc: tag)."
    else:
        notes = (
            "No rbc: or underscore barcode in sampled headers — barcode likely in read "
            "sequence."
        )
    return HeaderInspection(
        has_rbc=has_rbc,
        umi_in_comment=umi_in_comment,
        barcode_in_header=has_underscore or has_rbc,
        sample_headers=flat,
        fastq_files=[f"sra:{run}" for run in records_by_run],
        notes=notes,
    )


def preview_runs(
    run_accessions: list[str],
    *,
    n_reads: int = DEFAULT_READS,
    range_bytes: int = DEFAULT_RANGE_BYTES,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Preview several runs. Returns (records_by_run, source_by_run)."""
    records: dict[str, list[str]] = {}
    sources: dict[str, str] = {}
    for run in run_accessions:
        recs, source = preview_run(run, n_reads=n_reads, range_bytes=range_bytes)
        if recs:
            records[run] = recs
        sources[run] = source
    return records, sources
