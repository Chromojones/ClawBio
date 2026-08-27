#!/usr/bin/env python3
"""Stage 01 — is this study fetchable, and is it already on Flow?

Four checks before anything is built, because each one costs minutes here and hours later:
the accession resolves and is public; no run accession is present (asking for one imports its
whole parent experiment); the study is not already uploaded under different sample names; and
the total download fits in one import job.

The "already uploaded" check does not compare our own sample names. Those we choose, so a
study uploaded earlier under a different convention reports a clean import and is uploaded
twice. It searches Flow for the study's own identifiers instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.import_guards import check_import_size, check_run_expansion  # noqa: E402
from lib.results import ERROR, Finding  # noqa: E402
from lib.study_check import build_search_queries, parse_geo_response, summarise_hits  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "01_study"
REQUIRES = ("00_setup",)
OUTPUTS = ("study_check.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--geo-response", type=Path,
                        help="Cached GEO page text; omit to use what 00_setup recorded.")
    parser.add_argument("--sizes", type=Path,
                        help="JSON of {accession: {fastq_bytes: N}} from ENA.")
    parser.add_argument("--search-results", type=Path,
                        help="JSON of {query: response} from Flow's /search.")
    parser.add_argument("--allow-private", action="store_true",
                        help="Proceed even though the study is not public.")
    return parser


def _inputs(args, out):
    return [p for p in (args.geo_response, args.sizes, args.search_results) if p]


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

    rows = json.loads((out / "sheet_rows.json").read_text()) if (out / "sheet_rows.json").exists() else []
    if rows and args.sizes and args.sizes.exists():
        sizes = json.loads(args.sizes.read_text())
        parents = {a: v["experiment"] for a, v in sizes.items() if isinstance(v, dict) and v.get("experiment")}
        runs = {a: v["runs"] for a, v in sizes.items() if isinstance(v, dict) and v.get("runs")}
        findings += check_run_expansion([r.get("accession", "") for r in rows], parents, runs)
        findings += check_import_size(rows, sizes, parent_of_run=parents, runs_by_experiment=runs)

    if args.search_results and args.search_results.exists():
        hits = summarise_hits(json.loads(args.search_results.read_text()))
        report["already_uploaded"] = bool(hits.any_hits)
        lines.append(f"already on Flow: {'YES — ' + hits.summary if hits.any_hits else 'no'}")
        if hits.any_hits:
            findings.append(Finding(ERROR, hits.summary))
    elif accession:
        lines.append("search: not run — pass --search-results to check for a prior upload")
        report["search_queries"] = build_search_queries(rows) if rows else []

    (out / "study_check.json").write_text(json.dumps(report, indent=2) + "\n")
    return {"findings": [f for f in findings if f], "lines": lines, "note": accession}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
