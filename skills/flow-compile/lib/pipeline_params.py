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

from lib.protocol import ECLIP_METHODS  # single definition
from lib.results import Verdict


def is_eclip_method(experimental_method: str) -> bool:
    from lib.protocol import is_eclip_method as _impl
    return _impl(experimental_method)


def derive_clip_pipeline_params(
    inspection: HeaderInspection | None,
    *,
    five_prime_barcode: str = "",
    experimental_method: str = "",
    skip_umi_dedupe: str = "false",
) -> dict[str, str]:
    """
    Flow CLIP execution params from header inspection + confirmed barcodes.

    eCLIP / seCLIP:
    - UMI already in header (:rbc:) → move_umi_to_header=false, umi_separator=rbc:,
      encode_eclip=true (pre-extracted ENCODE-style dumps).
    - UMI still in read sequence (raw SRA) → move_umi_to_header=true, umi_separator=_,
      umi_header_format from 5′ barcode (typically 10N), encode_eclip=false.
      Flow Trim Galore + UMI tools extract to header with `_`, then umi_collapse.

    Other CLIP methods: same header rules; encode_eclip stays false.
    """
    eclip = is_eclip_method(experimental_method)

    if inspection and inspection.has_rbc:
        move = "false"
        separator = "rbc:"
        header_format = ""
        encode = "true" if eclip else "false"
    else:
        move = "true"
        separator = "_"
        header_format = barcode_to_header_format(five_prime_barcode)
        encode = "false"

    params: dict[str, str] = {
        "move_umi_to_header": move,
        "umi_separator": separator,
        "skip_umi_dedupe": skip_umi_dedupe,
        "crosslink_position": "start",
        "encode_eclip": encode,
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
        f"- **encode_eclip:** `{params.get('encode_eclip')}`",
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

def compare_confirmed_params(derived: dict, confirmed: dict) -> Verdict:
    """Do the confirmed parameters match the derived ones? Compared BY VALUE.

    The generated script used ``cmp -s``, a byte comparison. Two JSON objects holding identical
    parameters differ byte-for-byte whenever key order, indentation or a trailing newline
    changes, so a correctly confirmed run could be refused for a reformat. That is worse than
    annoying: a gate that blocks correct runs teaches its operator to work around it.

    The reverse held too. ``cmp`` reports no difference between two files that are equally
    wrong, so a parameter missing from both passed the gate.
    """
    derived = {str(k): str(v) for k, v in (derived or {}).items()}
    confirmed = {str(k): str(v) for k, v in (confirmed or {}).items()}
    if derived == confirmed:
        return Verdict(True, "confirmed parameters match the derived ones")

    problems = []
    for key in sorted(set(derived) | set(confirmed)):
        if key not in confirmed:
            problems.append(f"{key}: missing from the confirmed file (derived {derived[key]!r})")
        elif key not in derived:
            problems.append(f"{key}: in the confirmed file but never derived ({confirmed[key]!r})")
        elif derived[key] != confirmed[key]:
            problems.append(f"{key}: derived {derived[key]!r}, confirmed {confirmed[key]!r}")
    return Verdict(False, "; ".join(problems), evidence={"derived": derived, "confirmed": confirmed})
