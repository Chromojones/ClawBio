#!/usr/bin/env python3
"""Stage 11 — did the samples arrive as the sheet described them? CHECK.

Compares the live samples against the sheet that produced them, in Flow's keys. Differences are
written to `repair_edits.csv` for `flow_edit_samples.py` to apply; missing samples are reported
as a failed import. Samples pair to rows by name, which the import preserves.

Story: FAILURES.md#import-check
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

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
    return parser


def _inputs(args, out):
    sheets = [out / "import_sheet.csv", out / "upload_sheet.csv"]
    return [args.live_samples, *[s for s in sheets if s.exists()]]


def _sheet_rows(out: Path, line: str, study: dict) -> list[dict]:
    """The rows that produced the samples, in Flow's keys."""
    import pandas as pd

    from lib.sra_import import annotation_to_flow_row

    if line == "direct":
        st.require(out, "110_import")
        if not study.get("import_job"):
            raise CheckFailed("110_import ran as a dry run, so nothing was imported. Re-run it "
                              "with --submit, then verify.")
        return pd.read_csv(out / "import_sheet.csv", dtype=str).fillna("").to_dict("records")
    st.require(out, "210_upload")
    upload = pd.read_csv(out / "upload_sheet.csv", dtype=str).fillna("")
    return [annotation_to_flow_row(row) for row in upload.to_dict("records")]


def _write_edits(path: Path, repairs: list) -> list[str]:
    """Write the editable fields as a `flow_edit_samples.py` sample_id sheet; return the rest."""
    import csv

    from lib.vendor.flow_api.metadata.flow_edit_samples import WHITELIST_EDIT_FIELDS

    columns = [f for f in WHITELIST_EDIT_FIELDS if any(f in e.fields for e in repairs)]
    manual = sorted({f"{e.name}: {f}" for e in repairs for f in e.fields
                     if f not in WHITELIST_EDIT_FIELDS})
    if columns:
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample_id", *columns])
            writer.writeheader()
            for e in repairs:
                row = {f: e.fields[f] for f in columns if f in e.fields}
                if row:
                    writer.writerow({"sample_id": e.sample_id, **row})
    return manual


def body(args, out: Path) -> dict:
    study = st.study(out)
    sheet_rows = _sheet_rows(out, st.route(out)["line"], study)
    live = json.loads(args.live_samples.read_text())

    discrepancies = find_import_discrepancies(
        sheet_rows, live, project_id=study.get("project_id", ""))
    live_list = (live.get("samples") or []) if isinstance(live, dict) else live
    plan = build_repair_plan(sheet_rows, live_list, project_id=study.get("project_id", ""))
    missing = [e.name for e in plan if e.missing]
    repairs = [e for e in plan if not e.missing]

    (out / "verify_report.json").write_text(json.dumps({
        "discrepancies": [d.describe() if hasattr(d, "describe") else str(d) for d in discrepancies],
        "missing": missing,
        "repairs": [{"sample_id": e.sample_id, "fields": e.fields} for e in repairs],
    }, indent=2) + "\n")

    edits = out / "repair_edits.csv"
    edits.unlink(missing_ok=True)
    manual = _write_edits(edits, repairs) if repairs else []

    if not missing and not repairs:
        return {"lines": [f"{len(sheet_rows)} sample(s) match the sheet"], "note": "verified"}

    parts = []
    if missing:
        note = ""
        if len(live_list) < len(sheet_rows):
            note = (" If --live-samples came from a project listing, check it was not one page "
                    "(default page size 10).")
        parts.append(f"{len(missing)} sheet row(s) not imported: {', '.join(missing)}. A failed "
                     f"import is re-run, not repaired.{note}")
    if edits.exists():
        tool = SKILL_DIR / "lib" / "vendor" / "flow_api" / "metadata" / "flow_edit_samples.py"
        parts.append(f"{len(repairs)} sample(s) differ from the sheet; the edits are in {edits}. "
                     f"Apply them, then re-run 11_verify:\n"
                     f"  python3 {tool} --edits {edits} --dry-run\n"
                     f"  python3 {tool} --edits {edits} --yes")
    if manual:
        parts.append("not editable by flow_edit_samples.py, fix by hand: " + "; ".join(manual))
    raise CheckFailed("\n".join(parts))


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
