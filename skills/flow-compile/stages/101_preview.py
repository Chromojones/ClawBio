#!/usr/bin/env python3
"""Stage 101 — SRA-direct: look at the actual reads before deciding anything about them.

Pulls a few FASTQ records straight from ENA over a byte range, so the header state and read
layout come from the deposited data rather than from the paper's description of it. Papers
describe the protocol as designed; the archive holds what was uploaded, and on the studies
here they have differed often enough that the reads win.

Classifies the header into one of four states. Two booleans could not tell a raw header from
one whose randomer was already prepended by `eclipdemux`, and treating the second as the first
re-extracts five bases of real insert while deduplicating on sequence that is not the UMI.
Nothing errors when that happens, which is why it is checked here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.header_state import classify_headers  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "101_preview"
REQUIRES = ("06_route",)
OUTPUTS = ("header_preview.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--reads", type=int, default=5, help="Records to sample per accession.")
    parser.add_argument("--headers", type=Path,
                        help="Pre-sampled headers as JSON, instead of fetching from ENA.")
    parser.add_argument("--limit", type=int, default=2, help="Accessions to sample.")
    return parser


def _inputs(args, out):
    return [p for p in (args.headers, out / "sheet_rows.json") if p and Path(p).exists()]


def body(args, out: Path) -> dict:
    route = st.route(out)
    if route["line"] != "direct":
        raise CheckFailed(
            f"this run is on the {route['line']} line; 101_preview is the SRA-direct line. "
            f"Run stages/201_fetch.py instead."
        )

    if args.headers:
        headers = json.loads(Path(args.headers).read_text())
    else:
        from lib.sra_header_preview import preview_headers

        rows = json.loads((out / "sheet_rows.json").read_text())
        headers = []
        for row in rows[: args.limit]:
            headers += preview_headers(row["accession"], n_reads=args.reads)

    result = classify_headers(headers)
    if not result.ok:
        raise CheckFailed(result.reason)

    (out / "header_preview.json").write_text(json.dumps({
        "state": result.state,
        "counts": result.counts,
        "sampled": headers[:10],
    }, indent=2) + "\n")
    st.set_study(out, header_state=result.state)
    return {"lines": [f"header state: {result.state} ({len(headers)} header(s) sampled)"],
            "note": result.state}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
