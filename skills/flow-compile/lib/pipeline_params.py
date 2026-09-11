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
    """Params from a two-boolean header inspection. No stage uses it: `header_state.params_for_state`
    is the derivation, and handles the four header states this cannot tell apart.
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


#: Samples per execution. Above this, Flow executions become unreliable in practice; the figure
#: is operational rather than an API limit, which is why it lives here with the other analysis
#: parameters rather than being buried in a submission script.
MAX_SAMPLES_PER_EXECUTION = 18


def chunks_for(sample_count: int) -> int:
    """How many executions `sample_count` samples need at 18 per execution. The runner's `-n` is a
    number of batches, not samples per batch.
    """
    count = max(0, int(sample_count))
    if count <= MAX_SAMPLES_PER_EXECUTION:
        return 1
    return -(-count // MAX_SAMPLES_PER_EXECUTION)


def check_execution_batches(sample_count: int, num_chunks: int) -> list:
    """Does this split keep every execution within 18 samples? A rule `12_analysis` enforces."""
    from lib.results import ERROR, Finding, WARNING

    count = max(0, int(sample_count))
    chunks = int(num_chunks)

    if chunks < 1:
        return [Finding(ERROR, f"num_chunks must be at least 1, got {chunks}.")]

    per = -(-count // chunks) if chunks else count
    if per > MAX_SAMPLES_PER_EXECUTION:
        want = chunks_for(count)
        return [Finding(
            ERROR,
            f"{count} sample(s) across {chunks} execution(s) is {per} per execution, above the "
            f"ceiling of {MAX_SAMPLES_PER_EXECUTION}. Use {want} execution(s) instead.",
        )]
    if chunks > count > 0:
        return [Finding(
            WARNING,
            f"{chunks} execution(s) for {count} sample(s) leaves some empty. "
            f"{chunks_for(count)} would do.",
        )]
    return []
