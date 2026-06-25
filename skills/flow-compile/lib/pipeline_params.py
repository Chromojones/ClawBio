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


DEFAULT_TRIMGALORE_PARAMS = "--fastqc --length 10 -q 20"
UVCLAP_TRIMGALORE_PARAMS = (
    f"{DEFAULT_TRIMGALORE_PARAMS} --three_prime_clip_R1 10 --three_prime_clip_R2 5"
)


def derive_uvclap_post_umi_params(*, skip_umi_dedupe: str = "false") -> dict[str, str]:
    """
    uvCLAP after umi_tools extract: UMIs already in PE read headers.

    Adapter trimming and 3' readthrough clip run in Flow via Trim Galore
    (trimgalore_params). Authors clip 10 bp R1 / 5 bp R2 after adapter trim.
    """
    return {
        "move_umi_to_header": "false",
        "umi_separator": "_",
        "skip_umi_dedupe": skip_umi_dedupe,
        "crosslink_position": "start",
        "encode_eclip": "false",
        "star_params": DEFAULT_STAR_PARAMS,
        "trimgalore_params": UVCLAP_TRIMGALORE_PARAMS,
    }


def derive_flash_post_umi_params(*, skip_umi_dedupe: str = "false") -> dict[str, str]:
    """
    FLASH after umi_tools extract: UMI is already in read 1 headers.

    Do not set move_umi_to_header — Flow should not re-extract from read sequence.
    umi_separator _ tells umi_dedup how to parse the umi_tools suffix (readname_UMI).
    Upload *_1.umi.fastq.gz without removespace — spaces after the UMI are fine; samtools
    truncates at the first space before umi_dedup runs.
    """
    return {
        "move_umi_to_header": "false",
        "umi_separator": "_",
        "skip_umi_dedupe": skip_umi_dedupe,
        "crosslink_position": "start",
        "encode_eclip": "false",
        "star_params": DEFAULT_STAR_PARAMS,
    }


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
    if params.get("trimgalore_params"):
        lines.append(f"- **trimgalore_params:** `{params['trimgalore_params']}`")
    if params.get("umi_header_format"):
        lines.append(f"- **umi_header_format:** `{params['umi_header_format']}`")
    if inspection:
        lines.append(f"- **Header note:** {inspection.notes}")
    return "\n".join(lines) + "\n"


def write_analysis_params_hook(
    output_dir,
    params: dict[str, str],
    inspection: HeaderInspection | None = None,
    *,
    headers_path=None,
) -> None:
    """
    Agent hook for analysis params — present CONFIRM_ANALYSIS_PARAMS.md to the user,
    then create analysis_params.confirmed.json after review.
    """
    from pathlib import Path

    out = Path(output_dir)
    params_path = out / "pipeline_params.json"
    confirmed_path = out / "analysis_params.confirmed.json"
    hook_path = out / "CONFIRM_ANALYSIS_PARAMS.md"

    lines = [
        "# Analysis params hook — agent review required",
        "",
        "The agent should present these derived CLIP execution params and pause for confirmation.",
        "After review, create `analysis_params.confirmed.json` (copy of `pipeline_params.json`).",
        "",
        "```json",
        __import__("json").dumps(params, indent=2),
        "```",
        "",
        summarize_params_for_report(params, inspection).rstrip(),
        "",
        "## Inputs reviewed",
        "",
    ]
    if headers_path and Path(headers_path).exists():
        lines.append(f"- `headers.txt` — {Path(headers_path).name}")
    lines.extend(
        [
            f"- `pipeline_params.json` — written to `{params_path.name}`",
            "",
            "## Confirm",
            "",
            "```bash",
            f"cp {params_path} {confirmed_path}",
            "```",
            "",
            "`run_analysis.sh` refuses to submit until the confirmed file matches `pipeline_params.json`.",
        ]
    )
    hook_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
