#!/usr/bin/env python3
"""Stage 01 — is the study public, and is it already on Flow?

Both checks read evidence the agent supplies (`--geo-response`, `--search-results`). A check
without its evidence is reported as not run, never as passed. The size ceiling runs in
`109_sheet`, where the rows exist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.results import ERROR, Finding  # noqa: E402
from lib.study_check import parse_geo_response, summarise_hits  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "01_study"
REQUIRES = ("00_setup",)
OUTPUTS = ("study_check.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--geo-response", type=Path,
                        help="GEO SOFT text for the accession (form=text); omit to skip the check.")
    parser.add_argument("--search-results", type=Path,
                        help="JSON of {query: response} from Flow's /search; omit to skip the check.")
    parser.add_argument("--allow-private", action="store_true",
                        help="Proceed even though the study is not public.")
    return parser


def _inputs(args, out):
    return [p for p in (args.geo_response, args.search_results) if p]


def body(args, out: Path) -> dict:
    study = st.study(out)
    accession = study.get("accession", "")
    findings, report, lines = [], {"accession": accession}, []

    if args.geo_response and args.geo_response.exists():
        availability = parse_geo_response(accession, args.geo_response.read_text())
        report["public"] = availability.public
        report["reason"] = availability.reason
        lines.append(f"availability: {availability.describe()}")
        if not availability.public and not args.allow_private:
            raise CheckFailed(
                f"{accession} is not fetchable: {availability.reason}. "
                f"Pass --allow-private only if you have the data another way."
            )
    else:
        lines.append("availability: not checked — pass --geo-response "
                     "(reference/sra-direct-import.md §0)")

    if args.search_results and args.search_results.exists():
        hits = summarise_hits(json.loads(args.search_results.read_text()))
        report["already_uploaded"] = bool(hits.any_hits)
        lines.append(f"already on Flow: {'YES — ' + hits.summary if hits.any_hits else 'no'}")
        if hits.any_hits:
            findings.append(Finding(ERROR, hits.summary))
    else:
        lines.append("search: not run — pass --search-results to check for a prior upload")

    (out / "study_check.json").write_text(json.dumps(report, indent=2) + "\n")
    return {"findings": [f for f in findings if f], "lines": lines, "note": accession}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
