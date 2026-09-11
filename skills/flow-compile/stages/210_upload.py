#!/usr/bin/env python3
"""Stage 210 — local line: the upload sheet, and the command that uploads it.

Writes `upload_sheet.csv` and prints the vendored upload command, `--dry-run` first. The upload
path keeps `__annotation` columns, so no repair pass follows; `strandedness` is stripped because
the endpoint refuses it for CLIP.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402
from lib.import_guards import check_upload_fields, strip_rejected  # noqa: E402
from lib.results import WARNING, Finding  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "210_upload"
REQUIRES = ("108_params", "201_fetch")
OUTPUTS = ("upload_sheet.csv",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--sample-type", default="CLIP")
    return parser


def _inputs(args, out):
    return [out / "annotation.raw.csv", out / "pipeline_params.json", out / "fetch_plan.json"]


def body(args, out: Path) -> dict:
    import pandas as pd

    from lib.metadata_validate import normalize_annotation

    study = st.study(out)
    if not study.get("params_confirmed"):
        raise CheckFailed("analysis parameters were never confirmed; 108_params must pass first.")

    annotation = pd.read_csv(out / "annotation.raw.csv", dtype=str).fillna("")
    rows = annotation.to_dict("records")

    findings = []
    for row in rows:
        findings += check_upload_fields(row, sample_type=args.sample_type)
    rows = [strip_rejected(r, sample_type=args.sample_type) for r in rows]
    for row in rows:
        if "Purification Target Annotation" in row:
            row["Purification Target Annotation"] = normalize_annotation(
                row["Purification Target Annotation"])

    sheet = out / "upload_sheet.csv"
    pd.DataFrame(rows).to_csv(sheet, index=False)

    plan = json.loads((out / "fetch_plan.json").read_text()) if (out / "fetch_plan.json").exists() else {}
    fastq_dir = str(plan.get("fastq_dir") or "")
    project_id = str(study.get("project_id") or "")
    if not fastq_dir:
        findings.append(Finding(WARNING, "fetch_plan.json records no reads directory; re-run "
                                         "201_fetch with --fastq-dir <dir>, or fill in --base-dir."))
    if not project_id:
        findings.append(Finding(WARNING, "no project id was recorded at 00_setup; fill in "
                                         "--project-id."))

    command = [
        "python3", str(SKILL_DIR / "lib" / "vendor" / "flow_api" / "upload" / "uploadsample_flowbio_v6.py"),
        "--input", str(sheet), "--rows", f"1-{len(rows)}" if len(rows) > 1 else "1",
        "--project-id", project_id or "<project_id>", "--base-dir", fastq_dir or "<fastq_dir>",
    ]
    shown = " ".join(a if a.startswith("<") else shlex.quote(a) for a in command)
    lines = [f"{len(rows)} sample(s) prepared -> {sheet.name}",
             "check, then upload (run both yourself):",
             f"  {shown} --dry-run",
             f"  {shown}"]
    return {"findings": findings, "lines": lines, "note": f"{len(rows)} samples"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
