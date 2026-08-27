#!/usr/bin/env python3
"""Stage 201 — local line: fetch the reads, and clean headers only while that is still needed.

The local line exists for one reason now: a study absent from SRA/ENA. Header-comment UMIs
used to force it too, because the SAM QNAME whitespace boundary drops everything after the
first space, taking the UMI with it. That is being fixed inside the clip-seq pipeline by
running `removespace` there, so this stage performs the cleaning as a documented transitional
step and stops once the pipeline change ships.

The cleaning leaves `/` alone. Replacing it makes the last `_`-delimited field a constant `1`
across every read, and UMI-collapse then treats unrelated reads as duplicates of one another.
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
    parser.add_argument("--clean-headers", action="store_true",
                        help="Transitional: fold the header comment into the read name.")
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

    plan = {
        "fastq_dir": str(args.fastq_dir) if args.fastq_dir else "",
        "clean_headers": bool(args.clean_headers),
    }
    (out / "fetch_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    if args.clean_headers:
        lines.append("header cleaning: on (transitional; removespace moves into the pipeline)")
    return {"lines": lines or ["fetch plan recorded"], "note": "local"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
