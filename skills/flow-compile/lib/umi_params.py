"""Are the UMI execution params internally coherent?

Four consecutive studies — GSE75418, GSE68800, GSE80202, GSE58448 — were submitted with
``move_umi_to_header=true`` and **no** ``umi_separator``. The pipeline extracts the barcode
and writes it into the read name, then UMICollapse is told nothing about how to find it
again and dies::

    java.lang.IllegalStateException: No match found
        at umicollapse.util.SAMRead.getUMI(SAMRead.java:36)

E-MTAB-2700, which finished 605/605, carries the same shape **plus** ``"umi_separator": "_"``.

Two things make this worth a check rather than a habit:

* **It fails late.** Trimming, mapping and sorting all complete first, so a 7-sample study
  burns most of a run before anything says so.
* **It fails misleadingly.** The exception names ``SAMRead.getUMI``, so it reads as a problem
  with the UMI in the data. The LARP6 header case produces a byte-identical stack trace for
  an entirely different reason — there the UMI really was missing from the read name; here it
  is present and the parser was never told the delimiter.

These params contradict each other on their own terms, with no reference to the reads, so the
check is pure and runs before submission.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UmiParamCheck:
    ok: bool
    reason: str = ""


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def check_umi_params(params: dict, *, barcode: str = "") -> UmiParamCheck:
    """Validate the UMI params against each other, and optionally against the barcode.

    ``barcode`` is the sheet's ``five_prime_barcode_sequence`` (e.g. ``NNNCAATNN``). When
    given, its length must equal the ``umi_header_format`` length — the format is the mask
    the pipeline uses to carve the barcode off the read, so a mismatch silently takes the
    wrong number of bases.
    """
    move = _truthy(params.get("move_umi_to_header"))
    skip = _truthy(params.get("skip_umi_dedupe"))
    separator = str(params.get("umi_separator") or "").strip()
    fmt = str(params.get("umi_header_format") or "").strip()

    if not skip and not separator:
        where = "extracted into the read name" if move else "already in the read name"
        return UmiParamCheck(
            False,
            f"deduplication is on but `umi_separator` is absent. The UMI is {where}, and "
            f"UMICollapse has no delimiter to find it with — it dies with "
            f"`IllegalStateException: No match found` at SAMRead.getUMI, after mapping. "
            f"Set umi_separator (`_` for extracted barcodes, `rbc:` for iCount/ultraplex "
            f"headers), or set skip_umi_dedupe=true if there is genuinely no UMI.",
        )

    if move:
        if not fmt:
            return UmiParamCheck(
                False,
                "`move_umi_to_header=true` needs `umi_header_format` — the mask that says "
                "how many bases to carve off the read.",
            )
        if set(fmt.upper()) != {"N"}:
            return UmiParamCheck(
                False,
                f"`umi_header_format` must be all-N of the barcode's length, not {fmt!r}. "
                f"The metadata field carries the real sequence; the execution mask does not.",
            )
        if barcode and len(barcode.strip()) != len(fmt):
            return UmiParamCheck(
                False,
                f"barcode is {len(barcode.strip())} nt ({barcode.strip()}) but "
                f"`umi_header_format` is {len(fmt)} — the wrong number of bases would be "
                f"taken off every read.",
            )

    return UmiParamCheck(True)
