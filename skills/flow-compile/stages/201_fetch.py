#!/usr/bin/env python3
"""Stage 201 — local line: get the reads on disk. Nothing here renames them.

The local line exists for one reason now: a study absent from SRA/ENA. Header-comment UMIs
used to force it too, because the SAM QNAME whitespace boundary drops everything after the
first space and takes the UMI with it. `removespace` runs inside the clip-seq pipeline now, so
that is handled downstream.

**This stage deliberately does no header cleaning.** Cleaning renamed every read to
`*.cleaned.fastq.gz`, which made the annotation sheet's `File` column stale the instant it ran,
and rebuilding the sheet against the new names is what forced the user to run the whole
pipeline three times. With nothing renaming anything, the filenames chosen at annotation time
are the filenames uploaded, and the metadata is built in one pass.

Classifying the header still happens here. That reads the header; it does not rewrite the file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.header_state import classify_headers  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "201_fetch"
REQUIRES = ("06_route",)
OUTPUTS = ("fetch_plan.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--fastq-dir", type=Path, help="Where the reads are, or will be.")
    parser.add_argument("--headers", type=Path, help="Pre-sampled headers as JSON.")
    return parser


def _inputs(args, out):
    return [p for p in (args.headers, out / "annotation.raw.csv") if p and Path(p).exists()]


def body(args, out: Path) -> dict:
    route = st.route(out)
    if route["line"] != "local":
        raise CheckFailed(
            f"this run is on the {route['line']} line; 201_fetch is the local line. "
            f"Run stages/101_preview.py instead."
        )

    lines = []
    if args.headers and args.headers.exists():
        result = classify_headers(json.loads(args.headers.read_text()))
        if not result.ok:
            raise CheckFailed(result.reason)
        st.set_study(out, header_state=result.state)
        lines.append(f"header state: {result.state}")

    plan = {"fastq_dir": str(args.fastq_dir) if args.fastq_dir else ""}
    (out / "fetch_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    lines.append("header cleaning: none — removespace runs in the clip-seq pipeline")
    return {"lines": lines, "note": "local"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
