#!/usr/bin/env python3
"""Stage 13 — did every sample survive the run? CHECK.

The closing check. An execution reported as finished is not the same as an execution that
carried every sample through it, and the difference is invisible from the run's own status: a
sample that failed one process, or quietly completed fewer stages than its peers, leaves the
execution looking successful and the study short a replicate.

`--running` reports only hard failures. Mid-run, a sample still working through the pipeline
has legitimately not caught up, and calling that "dropped" would make the check useless exactly
when it is most wanted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.execution_audit import find_dropped_samples, format_report  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "13_audit"
REQUIRES = ("12_analysis",)
OUTPUTS = ("audit_report.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--processes", type=Path, required=True,
                        help="JSON list of process executions for the run.")
    parser.add_argument("--running", action="store_true",
                        help="The run is still going: report hard failures only.")
    parser.add_argument("--total-samples", type=int, default=0)
    return parser


def _inputs(args, out):
    return [args.processes]


def body(args, out: Path) -> dict:
    processes = json.loads(args.processes.read_text())
    dropped = find_dropped_samples(processes, finished=not args.running)

    total = args.total_samples or len({
        str(p.get("sample") or p.get("sample_name") or "") for p in processes
    } - {""})

    (out / "audit_report.json").write_text(json.dumps({
        "dropped": [{"sample": d.sample_name, "reason": d.reason,
                     "stages_completed": d.stages_completed,
                     "stages_expected": d.stages_expected} for d in dropped],
        "total_samples": total,
        "running": bool(args.running),
    }, indent=2) + "\n")

    if dropped:
        raise CheckFailed(
            f"{len(dropped)} of {total} sample(s) did not complete the run.",
            findings=[],
        )
    return {"lines": [format_report(dropped, total_samples=total)], "note": f"{total} clean"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
