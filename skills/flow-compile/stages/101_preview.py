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
from lib.sra_header_preview import inspection_from_header_records  # noqa: E402
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

    sources: dict[str, str] = {}
    if args.headers:
        headers = json.loads(Path(args.headers).read_text())
        records = {"supplied": list(headers)}
    else:
        import lib.sra_header_preview as preview

        rows = json.loads((out / "sheet_rows.json").read_text())[: args.limit]
        # The RUN, not the experiment: ENA serves FASTQ per SRR, and an SRX resolves to no
        # files — which would preview nothing and record a header state derived from no
        # headers. 02_index carries both accessions for exactly this reason.
        runs = [str(row.get("srr", "")).strip() for row in rows]
        if not all(runs):
            raise CheckFailed(
                "sheet_rows.json has no `srr` for every previewed sample. ENA serves FASTQ "
                "per run, so the preview needs the SRR; populate the srr_map's `srr` column "
                "and re-run 02_index."
            )
        records, sources = preview.preview_runs(runs, n_reads=args.reads)
        headers = [line for recs in records.values() for line in recs]

    # Classify the state AND ask whether the UMI will survive the fetch. These are different
    # questions: the state decides the params, while a UMI stranded in the header comment is
    # dropped at the SAM QNAME boundary and kills dedup after mapping, whatever the state.
    inspection = inspection_from_header_records(records, sources=sources)
    if inspection.umi_in_comment:
        raise CheckFailed(inspection.notes)

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
