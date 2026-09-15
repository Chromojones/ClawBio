#!/usr/bin/env python3
"""Stage 03 — the 5' barcode of every sample. HARD STOP.

Gathers evidence from the series matrix, GEO sample pages, the paper text and, with
`--fetch-reads`, the deposited reads themselves; writes `barcode_proposals.json` and
`CONFIRM_BARCODES.md`, and stops at exit 3. Supplying the confirmed file with
`--accept-proposals` is the approval. Composition finds an in-line block but cannot settle its
last base, so the length comes from the authors' pipeline config; reads processed before
submission are marked so the barcode is recorded as metadata only.

Story: FAILURES.md#read-structure
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.barcode_evidence import load_confirmed_proposals  # noqa: E402
from lib.barcode_extract import extract_barcodes_for_gsms, write_proposal_bundle  # noqa: E402
from stages._common import Gate, parser_for, run_stage  # noqa: E402

NAME = "03_barcodes"
REQUIRES = ("02_index",)
OUTPUTS = ("barcodes.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--geo-matrix", type=Path, help="Series matrix, for sample titles.")
    parser.add_argument("--geo-cache-dir", type=Path, help="Cached geo_GSM*.txt pages.")
    parser.add_argument("--paper-text", type=Path, action="append", default=[])
    parser.add_argument("--fetch-geo", action="store_true", help="Live-fetch GEO sample pages.")
    parser.add_argument("--compositions", type=Path,
                        help="JSON of {sample: [per-position deviation]}, to corroborate.")
    parser.add_argument("--fetch-reads", action="store_true",
                        help="Sample reads from ENA for the first runs, for the read structure.")
    parser.add_argument("--fetch-limit", type=int, default=3, help="Runs to sample reads from.")
    parser.add_argument("--accept-proposals", type=Path,
                        help="Confirmed barcode_proposals.json. Supplying it IS the approval.")
    return parser


def _inputs(args, out):
    return [p for p in (args.geo_matrix, args.compositions, args.accept_proposals,
                        *args.paper_text) if p]


def body(args, out: Path) -> dict:
    if args.accept_proposals:
        confirmed = load_confirmed_proposals(args.accept_proposals)
        if not confirmed:
            raise Gate(
                "the accept-proposals file has no confirmed rows. Set status=confirmed on the "
                "entries you have checked.",
                release=f"--accept-proposals {Path(args.accept_proposals).name}",
                artefact=str(args.accept_proposals),
            )
        payload = {gsm: {"five_prime": p.five_prime, "umi_barcode": p.umi_barcode,
                         "protocol": p.protocol, "notes": p.agent_notes}
                   for gsm, p in confirmed.items()}
        (out / "barcodes.json").write_text(json.dumps(payload, indent=2) + "\n")
        return {"lines": [f"{len(payload)} human-confirmed barcode(s)"],
                "note": f"{len(payload)} confirmed"}

    rows = json.loads((out / "sheet_rows.json").read_text()) if (out / "sheet_rows.json").exists() else []
    gsms = [r["gsm"] for r in rows if r.get("gsm")]
    matrix_samples = {}
    if args.geo_matrix:
        from lib.geo_matrix import parse_geo_matrix

        matrix_samples = parse_geo_matrix(args.geo_matrix)["samples"]
        gsms = gsms or list(matrix_samples)

    structures: dict = {}
    if args.fetch_reads:
        import lib.sra_header_preview as preview
        from lib.read_structure import classify_read_structure

        gsm_of = {r["srr"]: r["gsm"] for r in rows if r.get("srr") and r.get("gsm")}
        records, _ = preview.preview_runs(list(gsm_of)[: args.fetch_limit], n_reads=2000)
        structures = {run: classify_read_structure(preview.sequences_of(recs),
                                                   load_format=preview.sra_load_format(run))
                      for run, recs in records.items()}
        (out / "read_structure.json").write_text(json.dumps(
            {run: s.to_dict() for run, s in structures.items()}, indent=2) + "\n")

    proposals = extract_barcodes_for_gsms(
        gsms,
        paper_texts=[(p.name, p) for p in args.paper_text],
        geo_cache_dir=args.geo_cache_dir,
        fetch_geo=args.fetch_geo,
        sample_titles={g: matrix_samples.get(g, {}).get("title", "") for g in gsms},
        matrix_samples=matrix_samples,
        read_structures={gsm_of[run]: (run, s) for run, s in structures.items()},
    )
    path = write_proposal_bundle(out, proposals)

    corroboration = ""
    processed = [run for run, s in structures.items() if s.verdict == "processed"]
    if processed:
        corroboration = (f" Reads are PROCESSED for {', '.join(processed)} (read_structure.json): "
                         f"a confirmed barcode is metadata only; 108 will not extract it.")
    if args.compositions and args.compositions.exists():
        from lib.read_structure import infer_inline_layout

        layouts = {s: infer_inline_layout(d).describe()
                   for s, d in json.loads(args.compositions.read_text()).items()}
        (out / "barcode_composition.json").write_text(json.dumps(layouts, indent=2) + "\n")
        corroboration = f" Composition for {len(layouts)} sample(s) in barcode_composition.json."

    # The artefact is the rendered review file, not the JSON: it carries the evidence and the
    # quotes a person actually reads. The JSON is what they then edit and hand back, so both
    # are named — pointing at only the JSON left the review file discoverable by `ls`.
    raise Gate(
        f"{len(proposals)} barcode proposal(s) require approval before any upload.{corroboration} "
        f"Confirm the UMI length against the authors' pipeline config; composition cannot "
        f"settle its final base. Set status=confirmed in {path.name}, then hand it back.",
        release=f"--accept-proposals {path.name}",
        artefact=f"{out / 'CONFIRM_BARCODES.md'}  (evidence; edit {path.name} to confirm)",
    )


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
