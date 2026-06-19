"""Sample FASTQ read headers and write headers.txt for barcode inspection."""

from __future__ import annotations

import gzip
import re
from dataclasses import asdict, dataclass
from pathlib import Path

RBC_TAG = re.compile(r":rbc:", re.I)
UNDERSCORE_BARCODE = re.compile(r"_([ACGTNacgtn]+)(?:/|\s|$)")


@dataclass
class HeaderInspection:
    """Result of inspecting sampled read headers."""

    has_rbc: bool
    barcode_in_header: bool
    sample_headers: list[str]
    fastq_files: list[str]
    notes: str = ""

    @property
    def barcode_already_extracted(self) -> bool:
        return self.has_rbc


def _open_fastq(path: Path):
    if path.suffix == ".gz" or path.name.endswith(".fastq.gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def sample_read_headers(fastq_path: Path, *, n_reads: int = 5, include_sequence: bool = True) -> list[str]:
    """Return sampled FASTQ records as flat lines (4 lines per read when include_sequence)."""
    blocks: list[str] = []
    if not fastq_path.exists():
        return blocks
    with _open_fastq(fastq_path) as handle:
        reads = 0
        while reads < n_reads:
            header = handle.readline()
            if not header:
                break
            if not header.startswith("@"):
                continue
            if include_sequence:
                seq = handle.readline()
                plus = handle.readline()
                qual = handle.readline()
                if not qual:
                    break
                blocks.extend(
                    [header.rstrip("\n"), seq.rstrip("\n"), plus.rstrip("\n"), qual.rstrip("\n")]
                )
            else:
                blocks.append(header.rstrip("\n"))
            reads += 1
    return blocks


def find_fastq_for_srr(search_dir: Path, srr: str) -> Path | None:
    """Locate a FASTQ for an SRR under search_dir (non-recursive then shallow recursive)."""
    srr = srr.upper()
    patterns = [
        f"{srr}.fastq.gz",
        f"{srr}.fastq",
        f"{srr}_1.fastq.gz",
        f"{srr}_1.fastq",
    ]
    for name in patterns:
        candidate = search_dir / name
        if candidate.exists():
            return candidate
    for candidate in sorted(search_dir.glob(f"**/{srr}*.fastq*")):
        if candidate.is_file():
            return candidate
    return None


def inspect_header_lines(headers: list[str]) -> tuple[bool, bool]:
    """Return (has_rbc, barcode_in_header_via_underscore)."""
    at_lines = [h for h in headers if h.startswith("@")]
    has_rbc = any(RBC_TAG.search(h) for h in at_lines)
    has_underscore = any(UNDERSCORE_BARCODE.search(h) for h in at_lines)
    return has_rbc, has_underscore


def build_headers_txt(samples: list[tuple[str, list[str]]]) -> str:
    """Build headers.txt: five 4-line FASTQ records per SRR (matches hnRNPH layout)."""
    lines: list[str] = []
    for _label, block in samples:
        if not block:
            continue
        lines.extend(block)
    return "\n".join(lines) + ("\n" if lines else "")


def sample_headers_from_fastq_dir(
    srr_files: list[tuple[str, Path]],
    *,
    reads_per_file: int = 5,
) -> HeaderInspection:
    """
    Sample headers for each (srr, fastq_path) pair.
    srr_files: list of (srr_id, path) — path may be missing; skipped.
    """
    all_headers: list[str] = []
    used_files: list[str] = []
    sample_blocks: list[tuple[str, list[str]]] = []

    for srr, fq_path in srr_files:
        if fq_path is None or not fq_path.exists():
            continue
        headers = sample_read_headers(fq_path, n_reads=reads_per_file)
        if not headers:
            continue
        used_files.append(str(fq_path))
        sample_blocks.append((f"{srr} ({fq_path.name})", headers))
        all_headers.extend(headers)

    has_rbc, has_underscore = inspect_header_lines(all_headers)
    notes: list[str] = []
    if has_rbc:
        notes.append("Headers contain :rbc: — barcode already in read name.")
    elif has_underscore:
        notes.append("Headers contain underscore-suffixed barcode (not rbc: tag).")
    else:
        notes.append("No rbc: or underscore barcode in sampled headers — barcode likely in read sequence.")

    return HeaderInspection(
        has_rbc=has_rbc,
        barcode_in_header=has_underscore or has_rbc,
        sample_headers=all_headers,
        fastq_files=used_files,
        notes=" ".join(notes),
    )


def resolve_srr_fastq_paths(fastq_dir: Path | None, srr_ids: list[str]) -> list[tuple[str, Path | None]]:
    if not fastq_dir:
        return [(srr, None) for srr in srr_ids]
    return [(srr, find_fastq_for_srr(fastq_dir, srr)) for srr in srr_ids]


def inspection_to_dict(inspection: HeaderInspection) -> dict:
    return asdict(inspection)
