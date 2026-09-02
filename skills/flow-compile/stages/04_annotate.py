#!/usr/bin/env python3
"""Stage 04 — names, target, tag, agent, source, organism.

The sole writer of annotation content. `annotation.raw.csv` is what this stage produces;
later stages that touch filenames regenerate from it rather than editing in place, which is
what stops the old "run the command three times so the filenames catch up" loop.

Paper enrichment runs here when a PMID is present. When it is not, the field checks still
run: a series without `!Series_pubmed_id` previously got no validation at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from stages._common import parser_for, run_stage  # noqa: E402

NAME = "04_annotate"
REQUIRES = ("03_barcodes",)
OUTPUTS = ("annotation.raw.csv",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--geo-matrix", type=Path, required=True)
    parser.add_argument("--srr-map", type=Path, required=True)
    parser.add_argument("--paper-text", type=Path, action="append", default=[],
                        help="Full text for metadata enrichment; repeatable.")
    return parser


def _inputs(args, out):
    return [args.geo_matrix, args.srr_map, out / "barcodes.json", *args.paper_text]


def body(args, out: Path) -> dict:
    from lib.barcode_resolver import BarcodeResolution
    from lib.flow_annotate import (
        apply_eclip_crosslink_mate_filenames,
        build_annotation_table,
        load_srr_map,
    )
    from lib.geo_matrix import parse_geo_matrix
    from lib.paper_metadata_enrich import (
        collect_annotation_field_warnings,
        enrich_annotation_from_paper,
    )
    from lib.protocol import annotation_is_eclip

    matrix = parse_geo_matrix(args.geo_matrix)
    srr_map = load_srr_map(args.srr_map)
    # 03 writes plain JSON so the confirmed file stays reviewable by a person; rebuild the
    # objects the annotator expects rather than teaching it a second input shape.
    barcodes = {
        gsm: BarcodeResolution(
            gsm=gsm,
            five_prime=entry.get("five_prime", ""),
            three_prime=entry.get("umi_barcode", ""),
            protocol=entry.get("protocol", "generic"),
            confidence="high",
            sources=["human_confirmed"],
            notes=entry.get("notes", ""),
        )
        for gsm, entry in json.loads((out / "barcodes.json").read_text()).items()
    }

    annotation = build_annotation_table(matrix, srr_map, barcodes)
    pmid = matrix["series"].get("pubmed_id", "")
    lines = [f"{len(annotation)} annotation row(s)"]

    if pmid:
        blob = "\n\n".join(p.read_text(errors="replace") for p in args.paper_text)
        annotation, meta, warnings = enrich_annotation_from_paper(annotation, pmid, paper_text=blob)
        lines.append(f"paper: Scientist={meta.first_author or '?'}, PI={meta.last_author or '?'}, "
                     f"{len(warnings)} warning(s)")
    else:
        warnings = collect_annotation_field_warnings(annotation)
        lines.append(f"paper: skipped, no PMID on the series matrix; {len(warnings)} field warning(s)")

    # Paired-end eCLIP puts the randomer on read 2's 5' end with the crosslink immediately
    # after, so read 2 is the crosslink read and read 1 carries only the inline demultiplexing
    # barcode. Promoting the right mate here, in the sole writer of annotation content, means
    # exactly one place decides it. The old orchestrator called this twice with header cleaning
    # in between; it is idempotent, so the second call was redundant rather than load-bearing.
    is_eclip = bool(annotation_is_eclip(annotation))
    if is_eclip:
        annotation = apply_eclip_crosslink_mate_filenames(annotation)
        lines.append("eCLIP: read 2 promoted as the crosslink mate")

    (out / "annotation_warnings.json").write_text(
        json.dumps([str(w) for w in warnings], indent=2) + "\n")
    annotation.to_csv(out / "annotation.raw.csv", index=False)

    # sample_count feeds 12_analysis's 18-per-execution ceiling. Recorded here because this
    # stage is the sole writer of annotation content, so its row count IS the sample count;
    # a count nobody records is a ceiling nobody checks.
    st.set_study(out, eclip=is_eclip, sample_count=len(annotation))
    return {"lines": lines, "note": f"{len(annotation)} rows"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
