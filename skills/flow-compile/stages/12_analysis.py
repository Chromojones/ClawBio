#!/usr/bin/env python3
"""Stage 12 — submit the analysis. HARD STOP.

The last point at which a wrong parameter is cheap. Everything after this consumes compute and
produces results that look plausible whether or not the crosslink came from the right mate.

The reference genome is cross-checked against what the parameters imply, and the check has
three outcomes rather than two: agreed, disagreed, or NOT COMPARED. The third exists because a
cross-check that silently passes when it had nothing to compare is worse than no cross-check,
since it reads as confirmation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.reference_cross_check import cross_check_reference  # noqa: E402
from stages._common import CheckFailed, Gate, parser_for, run_stage  # noqa: E402

NAME = "12_analysis"
REQUIRES = ("108_params",)
OUTPUTS = ("analysis_submission.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--reference-params", type=Path, help="JSON of the chosen reference.")
    parser.add_argument("--no-reference-reason", default="",
                        help="Why no reference comparison was possible.")
    parser.add_argument("--accept-analysis", action="store_true",
                        help="Confirm the submission. This is the approval.")
    parser.add_argument("--submit", action="store_true")
    return parser


def _inputs(args, out):
    return [p for p in (out / "pipeline_params.json", args.reference_params) if p and Path(p).exists()]


def body(args, out: Path) -> dict:
    params = json.loads((out / "pipeline_params.json").read_text())
    study = st.study(out)
    if not study.get("params_confirmed"):
        raise CheckFailed("108_params was never confirmed; the parameters are unapproved.")

    reference = json.loads(args.reference_params.read_text()) if args.reference_params else {}
    check = cross_check_reference(params, reference,
                                  no_reference_run_reason=args.no_reference_reason)

    submission = {"params": params, "reference": reference, "cross_check": check.describe()}
    (out / "analysis_submission.json").write_text(json.dumps(submission, indent=2) + "\n")

    if not args.accept_analysis:
        raise Gate(
            f"analysis submission requires approval. Reference cross-check: {check.describe()}",
            release="--accept-analysis",
            artefact=str(out / "analysis_submission.json"),
        )
    lines = [f"cross-check: {check.describe()}"]
    lines.append("submitted" if args.submit else "dry run; re-run with --submit")
    return {"lines": lines, "note": check.describe()[:60]}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
