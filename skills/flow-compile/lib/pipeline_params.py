"""Analysis-stage helpers: the header format a barcode implies, the eCLIP test, and the
18-per-execution ceiling.
"""

from __future__ import annotations


def barcode_to_header_format(five_prime: str) -> str:
    """Execution umi_header_format: N repeated for barcode length (structure only)."""
    cleaned = (five_prime or "").strip().upper()
    if not cleaned:
        return "NNNNNNNNNNNNNNN"
    return "N" * len(cleaned)


def is_eclip_method(experimental_method: str) -> bool:
    from lib.protocol import is_eclip_method as _impl
    return _impl(experimental_method)


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
