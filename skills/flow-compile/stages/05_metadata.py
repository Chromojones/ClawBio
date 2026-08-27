#!/usr/bin/env python3
"""Stage 05 — is every field defensible? HARD STOP.

Validates the whole annotation in one pass rather than field by field, so a reviewer sees one
list and can judge the study as a whole. Piecewise validation produced the failure where 41
spurious antibody warnings buried the two real ones.

Errors gate; warnings print and continue. `--accept-metadata` is the decision, and like the
barcode gate it is a human artefact rather than a flag that merely silences output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.results import ERROR, render_findings  # noqa: E402
from stages._common import Gate, parser_for, run_stage  # noqa: E402

NAME = "05_metadata"
REQUIRES = ("04_annotate",)
OUTPUTS = ("metadata_report.md",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--accept-metadata", action="store_true",
                        help="Confirm the reported issues have been reviewed.")
    return parser


def _inputs(args, out):
    return [out / "annotation.raw.csv"]


def body(args, out: Path) -> dict:
    import pandas as pd

    from lib.metadata_validate import validate_annotation_table

    annotation = pd.read_csv(out / "annotation.raw.csv", dtype=str).fillna("")
    issues = validate_annotation_table(annotation)
    errors = [i for i in issues if i.severity == ERROR]

    report = render_findings(issues, title="metadata", total=len(annotation))
    (out / "metadata_report.md").write_text(report + "\n")
    (out / "metadata_issues.json").write_text(
        json.dumps([i.describe() for i in issues], indent=2) + "\n")

    if errors and not args.accept_metadata:
        raise Gate(
            f"{len(errors)} metadata error(s) and {len(issues) - len(errors)} warning(s) "
            f"require review before upload.",
            release="--accept-metadata",
            artefact=str(out / "metadata_report.md"),
        )

    lines = [f"{len(errors)} error(s), {len(issues) - len(errors)} warning(s)"]
    if errors:
        lines.append("accepted by --accept-metadata")
    return {"lines": lines, "note": f"{len(issues)} issue(s)"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
