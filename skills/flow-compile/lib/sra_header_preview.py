"""Remote FASTQ header preview — the gate before `flowbio samples import`.

The SRA-direct import never downloads reads, but the pipeline params still depend on what
the read headers look like (`:rbc:` present → UMI already extracted). This module fetches
just enough of the gzipped FASTQ to read a few records.

**ENA is the primary source and that matters — but not for the reason once recorded here.**
ENA renders the defline as ``@<run>.<n> <original spot name>``::

    @SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1

This is the form Flow itself fetches, which is the whole point: the preview must see the
study exactly as the import will.

The old note claimed ``fastq-dump`` rewrites deflines to ``@SRR…N`` even with ``--origfmt``
and so destroys ``:rbc:`` detection. It does neither. Measured on SRR33628723 (sra-tools
3.2.1), ``:rbc:`` survives every form; what differs is only *where* it sits::

    ENA fastq_ftp         @SRR33628723.1 NS500784:…:1rbc:TAGGATAAA/1   comment
    fastq-dump (default)  @SRR33628723.1 NS500784:…:1rbc:TAGGATAAA length=83   comment
    fastq-dump --origfmt  @NS500784:…:1rbc:TAGGATAAA                  read name

The UMI is lost at the **whitespace boundary**, not at dump time: the SAM QNAME ends at the
first space, so aligners drop the comment. The fallback is still not trusted, for the
inverse reason — ``--origfmt`` deletes the comment field entirely, so the check that refuses
SRA-direct has no space to find. See ``umi_is_stranded_in_comment``.

The pure functions here (`parse_ena_fastq_urls`, `inspection_from_header_records`) carry
all the logic and are unit-tested; the network wrappers are thin.
"""

from __future__ import annotations

import gzip
import subprocess
import urllib.request
import zlib
from pathlib import Path

from lib.fastq_headers import (
    RBC_TAG,
    HeaderInspection,
    build_headers_txt,
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
    """Extract FASTQ URLs from an ENA filereport TSV.

    ENA prepends a ``run_accession`` column, and paired runs put both mates in one
    semicolon-joined field — so the ftp path is located by **content**, never by index.
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

    ENA and SRA render the defline as ``@<run>.<n> <original spot name>``, so a UMI carried by
    the original header lands after the first space — in the comment, which every aligner
    discards at the SAM QNAME boundary. The BAM read name then has no UMI and UMICollapse
    fails with "No match found".

    ``source`` matters because the fallback fetch does not show that form. ``fastq-dump
    --origfmt`` prints the original spot name ALONE — no accession prefix, therefore no
    comment field and no space to find. Reading that as "not stranded" is how the refusal
    below silently disappears on the fallback path. The verdict is still decidable, because
    the rendering is deterministic: whatever ``--origfmt`` shows in the name is exactly what
    becomes the comment when ENA prefixes the accession, which is the form Flow fetches.

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
    """Build a HeaderInspection from remote snippets, with no local FASTQ on disk.

    Reuses `fastq_headers.inspect_header_lines`, the same pure check the local path uses,
    so remote and local previews cannot diverge.

    ``sources`` names how each run was fetched. It changes the comment verdict rather than
    only annotating it: the fallback's deflines carry no comment field, so the whitespace the
    check reads is absent for a reason that is not safety.
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


def preview_to_headers_text(records_by_run: dict[str, list[str]]) -> str:
    return build_headers_txt([(run, recs) for run, recs in records_by_run.items()])


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


def write_headers_preview(
    output_dir: Path,
    records_by_run: dict[str, list[str]],
    sources: dict[str, str] | None = None,
) -> Path:
    """Write headers.txt plus a provenance note naming the fetch source per run."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "headers.txt"
    path.write_text(preview_to_headers_text(records_by_run), encoding="utf-8")

    if sources:
        lines = ["# Header preview provenance", ""]
        for run, source in sources.items():
            if source == "ena":
                note = "ENA byte-range — original submitted headers preserved"
            elif source == "fastq-dump":
                note = ("fastq-dump --origfmt fallback — original spot name only, no "
                        "comment field; the comment verdict is inferred, not observed")
            else:
                note = "unavailable — no header evidence"
            lines.append(f"- `{run}`: {source} ({note})")
        lines.append("")
        (output_dir / "headers_provenance.md").write_text("\n".join(lines), encoding="utf-8")
    return path
