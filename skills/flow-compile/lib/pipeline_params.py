"""Derive Flow CLIP pipeline params from FASTQ header inspection and barcode format."""

from __future__ import annotations

from lib.fastq_headers import HeaderInspection

DEFAULT_STAR_PARAMS = (
    "--outFilterMultimapNmax 100 --outFilterMultimapScoreRange 1 --outSAMattributes All "
    "--alignSJoverhangMin 8 --alignSJDBoverhangMin 1 --outFilterType BySJout "
    "--alignIntronMin 20 --alignIntronMax 1000000 --outFilterScoreMin 10 "
    "--alignEndsType Extend5pOfRead1 --twopassMode Basic --limitOutSJcollapsed 4000000"
)


def barcode_to_header_format(five_prime: str) -> str:
    """Execution umi_header_format: N repeated for barcode length (structure only)."""
    cleaned = (five_prime or "").strip().upper()
    if not cleaned:
        return "NNNNNNNNNNNNNNN"
    return "N" * len(cleaned)


def derive_clip_pipeline_params(
    inspection: HeaderInspection | None,
    *,
    five_prime_barcode: str = "",
    skip_umi_dedupe: str = "false",
) -> dict[str, str]:
    """
    Flow CLIP execution params.

    - rbc: in header → barcode already extracted → move_umi_to_header false, umi_separator rbc:
    - otherwise → extract to header with underscore separator
    """
    if inspection and inspection.has_rbc:
        move = "false"
        separator = "rbc:"
        header_format = ""
    else:
        move = "true"
        separator = "_"
        header_format = barcode_to_header_format(five_prime_barcode)

    params: dict[str, str] = {
        "move_umi_to_header": move,
        "umi_separator": separator,
        "skip_umi_dedupe": skip_umi_dedupe,
        "crosslink_position": "start",
        "encode_eclip": "false",
        "star_params": DEFAULT_STAR_PARAMS,
    }
    if header_format:
        params["umi_header_format"] = header_format
    return params


def summarize_params_for_report(params: dict[str, str], inspection: HeaderInspection | None) -> str:
    lines = [
        "## Flow pipeline params (from header inspection)",
        "",
        f"- **move_umi_to_header:** `{params.get('move_umi_to_header')}`",
        f"- **umi_separator:** `{params.get('umi_separator')}`",
    ]
    if params.get("umi_header_format"):
        lines.append(f"- **umi_header_format:** `{params['umi_header_format']}`")
    if inspection:
        lines.append(f"- **Header note:** {inspection.notes}")
    return "\n".join(lines) + "\n"
