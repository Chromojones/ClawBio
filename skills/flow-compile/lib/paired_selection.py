"""Guard `csv_params.samplesheet.paired` against the study's actual read layout.

`paired` selects which mate the pipeline analyses: ``both``, ``first`` or ``second``. On
PAIRED-end data all three are meaningful — ENCODE3 eCLIP puts the crosslink on read 2, so
``second`` is right for PARP13 and GSE290281.

On SINGLE-end data there is no mate to select, and asking for one empties the samplesheet.
GSE75418 and GSE68800 were both submitted with ``second``, inherited from a submit script
copied out of a paired-end study. The pipeline wrote rows with both read columns blank::

    MSI1_U251_Hs_WT_rep3_SRX1023997,1,,

and failed at ``SAMPLE_BASE_SAMPLESHEET_CHECK``::

    ERROR: Please check samplesheet -> Invalid number of populated columns (minimum = 3)!

That message says nothing about reads, mates or ``paired``, so it reads as a malformed sheet
rather than an impossible mate selection — the cause is a copied default two files away. Both
executions had to be deleted and resubmitted.

ENA's ``library_layout`` field states SINGLE or PAIRED per run, so this is answerable before
submitting rather than ~40 s into a run.

This module is pure; the caller supplies the layouts.
"""

from __future__ import annotations

from dataclasses import dataclass

_VALID = ("both", "first", "second")


@dataclass
class PairedCheck:
    ok: bool
    reason: str = ""


def check_paired_selection(choice: str, *, layouts: set[str]) -> PairedCheck:
    """Is ``choice`` coherent with the study's read layout?

    ``layouts`` is the set of ENA ``library_layout`` values across the study's runs. An empty
    set means the layout was never established, which is refused rather than assumed — the
    whole point is to stop guessing about mates.
    """
    choice = str(choice or "").strip().lower()
    if choice not in _VALID:
        return PairedCheck(False, f"{choice!r} is not one of {_VALID}; anything else is silently ignored")

    normalised = {str(x).strip().upper() for x in layouts if str(x).strip()}
    if not normalised:
        return PairedCheck(False, "read layout is unknown — read ENA's `library_layout` before choosing a mate")
    if normalised == {"SINGLE"}:
        if choice == "both":
            return PairedCheck(True)
        return PairedCheck(
            False,
            f"paired={choice!r} on SINGLE-end data: there is no mate to select, and the "
            f"samplesheet ends up with both read columns blank. Use 'both'.",
        )
    if normalised == {"PAIRED"}:
        return PairedCheck(True)
    return PairedCheck(
        False,
        f"mixed read layouts {sorted(normalised)} in one submission — split the study by "
        f"layout, or the single-end rows will lose their reads",
    )
