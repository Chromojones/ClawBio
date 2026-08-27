#!/usr/bin/env python3
"""Stage 109 — build and check the accession sheet. CHECK.

The sheet is the entire contract with `flowbio samples import`, and three of its rules were
learned by having them fail.

Every accession must be an EXPERIMENT. A run is accepted and silently expanded to its parent,
so a sheet of runs imports more than it names and still reports COMPLETED.

`strandedness` must not appear for CLIP. `batch-template --sample-type CLIP` lists it as
required and the endpoint rejects it, which cost ten uploads before it was stripped here.

The whole job must fit. A study of 132.7 GB failed with `exit status 4` while ENA was provably
healthy; the bytes counted are the effective ones, so a sheet of runs is measured as the
experiments it will actually pull.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.import_guards import check_import_size, check_upload_fields, strip_rejected  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "109_sheet"
REQUIRES = ("108_params",)
OUTPUTS = ("import_sheet.csv",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--sizes", type=Path, help="JSON of {accession: {fastq_bytes: N}}.")
    parser.add_argument("--sample-type", default="CLIP")
    return parser


def _inputs(args, out):
    return [p for p in (out / "annotation.raw.csv", args.sizes) if p and Path(p).exists()]


def body(args, out: Path) -> dict:
    import pandas as pd

    from lib.sra_import import build_import_sheet, write_import_sheet

    annotation = pd.read_csv(out / "annotation.raw.csv", dtype=str).fillna("")
    study = st.study(out)

    sheet = build_import_sheet(annotation, sample_type=args.sample_type,
                               project_id=study.get("project_id", ""))
    rows = sheet.to_dict("records")

    findings = []
    for row in rows:
        findings += check_upload_fields(row, sample_type=args.sample_type)
    rows = [strip_rejected(r, sample_type=args.sample_type) for r in rows]

    if args.sizes and args.sizes.exists():
        sizes = json.loads(args.sizes.read_text())
        parents = {a: v["experiment"] for a, v in sizes.items()
                   if isinstance(v, dict) and v.get("experiment")}
        runs = {a: v["runs"] for a, v in sizes.items() if isinstance(v, dict) and v.get("runs")}
        findings += check_import_size(rows, sizes, parent_of_run=parents, runs_by_experiment=runs)
    else:
        findings.append(_no_sizes())

    path = write_import_sheet(out, sheet)
    return {"findings": findings,
            "lines": [f"{len(rows)} row(s) -> {path.name}",
                      f"project column: {'set' if study.get('project_id') else 'ABSENT'}"],
            "note": f"{len(rows)} rows"}


def _no_sizes():
    from lib.results import WARNING, Finding

    return Finding(WARNING, "no --sizes given, so the import size is unchecked. A 132.7 GB job "
                            "failed with `exit status 4` while ENA was healthy.")


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
