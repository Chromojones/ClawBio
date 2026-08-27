#!/usr/bin/env python3
"""Stage 210 — local line: upload the reads with their metadata.

Unlike the import job, the upload path honours `__annotation` columns, so annotations arrive
with the samples and need no repair afterwards. `strandedness` is still stripped: the CLIP
template lists it as required and the endpoint refuses it.

Deleting a read mate to correct a mistake silently breaks the sample. Upload only the mate
you want.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.import_guards import check_upload_fields, strip_rejected  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "210_upload"
REQUIRES = ("108_params", "201_fetch")
OUTPUTS = ("upload_sheet.csv",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--sample-type", default="CLIP")
    parser.add_argument("--submit", action="store_true", help="Actually upload.")
    return parser


def _inputs(args, out):
    return [out / "annotation.raw.csv", out / "pipeline_params.json"]


def body(args, out: Path) -> dict:
    import pandas as pd

    study = st.study(out)
    if not study.get("params_confirmed"):
        raise CheckFailed("analysis parameters were never confirmed; 108_params must pass first.")

    annotation = pd.read_csv(out / "annotation.raw.csv", dtype=str).fillna("")
    rows = annotation.to_dict("records")

    findings = []
    for row in rows:
        findings += check_upload_fields(row, sample_type=args.sample_type)
    rows = [strip_rejected(r, sample_type=args.sample_type) for r in rows]

    pd.DataFrame(rows).to_csv(out / "upload_sheet.csv", index=False)
    lines = [f"{len(rows)} sample(s) prepared -> upload_sheet.csv"]
    if not args.submit:
        lines.append("dry run; re-run with --submit to upload")
    return {"findings": findings, "lines": lines, "note": f"{len(rows)} samples"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
