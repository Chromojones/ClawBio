#!/usr/bin/env python3
"""Stage 02 — the samples, and the runs behind them.

Reads the GEO series matrix and the SRR map into one index the rest of the run works from.
Nothing here is inferred: the matrix names the samples, the map names their runs, and a
disagreement between the two is reported rather than reconciled.

The accession written per row is the EXPERIMENT, never the run. Asking Flow to import a run
imports its whole parent experiment, so a sheet of run accessions fetches more than it names
and reports COMPLETED while doing so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.results import ERROR, WARNING, Finding  # noqa: E402
from stages._common import parser_for, run_stage  # noqa: E402

NAME = "02_index"
REQUIRES = ("01_study",)
OUTPUTS = ("sheet_rows.json", "index.json")


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--geo-matrix", type=Path, required=True, help="GEO series matrix file.")
    parser.add_argument("--srr-map", type=Path, required=True, help="TSV of gsm/srx/srr.")
    parser.add_argument("--sample-type", default="CLIP")
    return parser


def _inputs(args, out):
    return [args.geo_matrix, args.srr_map]


def body(args, out: Path) -> dict:
    from lib.flow_annotate import load_srr_map, parse_geo_matrix

    matrix = parse_geo_matrix(args.geo_matrix)
    srr_map = load_srr_map(args.srr_map)

    gsms_in_matrix = set(matrix["samples"])
    gsms_in_map = set(srr_map["gsm"].astype(str))
    findings = []
    if missing := sorted(gsms_in_map - gsms_in_matrix):
        findings.append(Finding(
            ERROR, f"srr_map names {len(missing)} GSM(s) absent from the matrix: "
                   f"{', '.join(missing[:5])}"))
    if extra := sorted(gsms_in_matrix - gsms_in_map):
        findings.append(Finding(
            WARNING, f"{len(extra)} GSM(s) in the matrix have no runs mapped and will not be "
                     f"imported: {', '.join(extra[:5])}"))

    rows = []
    for gsm, group in srr_map.groupby(srr_map["gsm"].astype(str)):
        srx = sorted({str(v).strip() for v in group.get("srx", []) if str(v).strip()})
        if not srx:
            findings.append(Finding(
                ERROR, f"{gsm} has no SRX. A run accession imports its whole parent "
                       f"experiment, so the sheet must name the experiment.", subject=gsm))
            continue
        rows.append({"accession": srx[0], "sample_type": args.sample_type, "gsm": gsm})

    (out / "sheet_rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (out / "index.json").write_text(json.dumps({
        "gse": matrix["series"].get("geo_accession", ""),
        "pmid": matrix["series"].get("pubmed_id", ""),
        "title": matrix["series"].get("title", ""),
        "gsm_count": len(matrix["samples"]),
        "row_count": len(rows),
    }, indent=2) + "\n")

    st.set_study(out, gse=matrix["series"].get("geo_accession", ""),
                 pmid=matrix["series"].get("pubmed_id", ""))
    return {
        "findings": findings,
        "lines": [f"{len(matrix['samples'])} GSM in matrix, {len(rows)} sheet row(s)"],
        "note": f"{len(rows)} rows",
    }


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
