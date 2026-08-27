#!/usr/bin/env python3
"""Stage 12 — submit the analysis. A check, not a gate.

This was the fourth hard stop and no longer is. Once the parameters are approved at 108 there
is nothing left for a person to decide here: the parameters *are* the decision, and asking for
them to be confirmed a second time at submission asks the same question twice. A gate that
re-asks a settled question is how gates lose their meaning.

What genuinely made submission risky was never the parameters but the batch size, and that is
a rule rather than a judgement: no more than 18 samples per execution. So it is enforced,
along with two things that must already hold — 108 confirmed, and the reference agreeing with
what the parameters imply.

The reference cross-check has three outcomes rather than two: agreed, disagreed, or NOT
COMPARED. The third exists because a cross-check that silently passes when it had nothing to
compare is worse than none, since it reads as confirmation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402
from lib.pipeline_params import (  # noqa: E402
    MAX_SAMPLES_PER_EXECUTION,
    check_execution_batches,
    chunks_for,
)
from lib.reference_cross_check import cross_check_reference  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "12_analysis"
REQUIRES = ("108_params",)
OUTPUTS = ("analysis_submission.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--reference-params", type=Path, help="JSON of the chosen reference.")
    parser.add_argument("--no-reference-reason", default="",
                        help="Why no reference comparison was possible.")
    parser.add_argument("--analysis-script", type=Path,
                        help="Path to flowrunanalysis_flowbio.py, for the generated runner.")
    parser.add_argument("--samples", type=int, default=0,
                        help="Sample count; defaults to what 02_index recorded.")
    parser.add_argument("--chunks", type=int, default=0,
                        help="Executions to split across. Derived from --samples if omitted.")
    parser.add_argument("--submit", action="store_true")
    return parser


def _inputs(args, out):
    return [p for p in (out / "pipeline_params.json", args.reference_params) if p and Path(p).exists()]


def body(args, out: Path) -> dict:
    # Imported here rather than at module scope: it pulls pandas, which makes `--help` slow and
    # turns any import-time warning into stderr noise on a plain usage error.
    from lib.flow_stages import write_analysis_script

    params = json.loads((out / "pipeline_params.json").read_text())
    study = st.study(out)
    if not study.get("params_confirmed"):
        raise CheckFailed("108_params was never confirmed; the parameters are unapproved.")

    reference = json.loads(args.reference_params.read_text()) if args.reference_params else {}
    check = cross_check_reference(params, reference,
                                  no_reference_run_reason=args.no_reference_reason)

    submission = {"params": params, "reference": reference, "cross_check": check.describe()}
    (out / "analysis_submission.json").write_text(json.dumps(submission, indent=2) + "\n")

    # The batch ceiling is the real submission risk, and it is a rule rather than a judgement.
    sample_count = args.samples or int(study.get("sample_count") or 0)
    chunks = args.chunks or chunks_for(sample_count)
    findings = check_execution_batches(sample_count, chunks) if sample_count else []

    lines = [
        f"cross-check: {check.describe()}",
        f"{sample_count or 'unknown'} sample(s) across {chunks} execution(s)"
        + (f", {-(-sample_count // chunks)} each" if sample_count else ""),
    ]
    if not sample_count:
        from lib.results import Finding, WARNING

        findings = [Finding(WARNING, "sample count unknown, so the "
                                     f"{MAX_SAMPLES_PER_EXECUTION}-per-execution ceiling was "
                                     "not checked. Pass --samples.")]

    # The generated runner carries the confirmed-parameters check, which compares the derived
    # and confirmed files BY VALUE. Generating it here is what puts that check in the path the
    # stages actually take; it previously lived in a script nothing produced.
    script_path = args.analysis_script or (
        SKILL_DIR / "lib" / "vendor" / "flow_api" / "analysis" / "flowrunanalysis_flowbio.py")
    runner = write_analysis_script(
        out,
        analysis_script=Path(script_path),
        project_id=study.get("project_id", ""),
        pipeline_params=params,
        sample_name_filter=study.get("sample_name_filter", ""),
        experimental_method=st.route(out).get("protocol", ""),
        num_chunks=chunks,
    )
    lines.append(f"runner: {runner.name} (confirm params, then run it)")
    lines.append("submitted" if args.submit else "dry run; re-run with --submit")
    return {"findings": findings, "lines": lines, "note": check.describe()[:60]}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
