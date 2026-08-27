#!/usr/bin/env python3
"""Stage 11 — did the samples arrive as the sheet described them? CHECK, then repair.

The import job discards `__annotation` columns. They are sent exactly as the upload path sends
them — every non-reserved column goes into one flat metadata dict — and the loss happens
server-side, so nothing in the job output says a field went missing. This stage compares the
sheet against what Flow actually holds and repairs the difference through
`POST /samples/{id}/edit`, which does honour the same flat key.

Samples are paired to rows by name, which the import preserves verbatim. Rows with no sample
and samples with no row are both reported: an unpaired sample is usually debris from an earlier
attempt, and deleting the wrong one is expensive.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.import_check import build_repair_plan, find_import_discrepancies  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "11_verify"
REQUIRES = ("06_route",)
OUTPUTS = ("verify_report.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--live-samples", type=Path, required=True,
                        help="JSON list of GET /samples/{id} payloads.")
    parser.add_argument("--repair", action="store_true", help="Apply the repair plan.")
    return parser


def _inputs(args, out):
    return [args.live_samples]


def body(args, out: Path) -> dict:
    import pandas as pd

    study = st.study(out)
    annotation = pd.read_csv(out / "annotation.raw.csv", dtype=str).fillna("")
    sheet_rows = annotation.to_dict("records")
    live = json.loads(args.live_samples.read_text())

    discrepancies = find_import_discrepancies(
        sheet_rows, live, project_id=study.get("project_id", ""))
    plan = build_repair_plan(sheet_rows, live, project_id=study.get("project_id", ""))

    (out / "verify_report.json").write_text(json.dumps({
        "discrepancies": [d.describe() if hasattr(d, "describe") else str(d) for d in discrepancies],
        "repairs": [{"sample_id": e.sample_id, "fields": e.fields} for e in plan],
    }, indent=2) + "\n")

    lines = [f"{len(discrepancies)} discrepancy(ies), {len(plan)} sample(s) need repair"]
    if plan and not args.repair:
        raise CheckFailed(
            f"{len(plan)} sample(s) do not match the sheet. Review verify_report.json, then "
            f"re-run with --repair to apply the edits."
        )
    if plan:
        lines.append("repairs applied" if args.repair else "")
    return {"lines": [ln for ln in lines if ln], "note": f"{len(plan)} repairs"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
