#!/usr/bin/env python3
"""Stage 108 — the analysis parameters. HARD STOP. On both lines.

Everything that decides what the pipeline does to the reads is settled in one place: where the
UMI is, how long it is, which mate carries the crosslink, and whether the header survives the
separator it will be split on. These have to agree with each other, and the failures when they
do not are silent ones. A UMI re-extracted from a header that already holds it strips real
insert. A crosslink taken from the wrong mate gives peaks in the wrong places. Neither errors.

That is why this is a gate rather than a check: the parameters are derived and shown, and a
person confirms them against the study's own pipeline config before anything runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.header_state import params_for_state  # noqa: E402
from lib.import_guards import check_paired_selection  # noqa: E402
from lib.read_structure import check_umi_params  # noqa: E402
from stages._common import CheckFailed, Gate, parser_for, run_stage  # noqa: E402

NAME = "108_params"
REQUIRES = ("06_route",)
OUTPUTS = ("pipeline_params.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--paired", choices=("both", "first", "second"), default="",
                        help="Which mate to analyse. Defaults to the protocol's own answer.")
    parser.add_argument("--layouts", default="",
                        help="Comma-separated ENA library layouts, e.g. PAIRED or SINGLE.")
    parser.add_argument("--umi-length", type=int, default=0,
                        help="From the authors' pipeline config, NOT from composition.")
    parser.add_argument("--accept-params", action="store_true",
                        help="Confirm the derived parameters. This is the approval.")
    return parser


def _inputs(args, out):
    return [p for p in (out / "header_preview.json", out / "barcodes.json") if p.exists()]


def body(args, out: Path) -> dict:
    route = st.route(out)
    study = st.study(out)
    protocol = route.get("protocol", "")

    state = study.get("header_state", "")
    if not state:
        raise CheckFailed(
            "no header state recorded. Run 101_preview (direct) or 201_fetch (local) first: "
            "deriving UMI parameters without looking at a header is how a randomer that was "
            "already moved gets extracted a second time."
        )

    params = dict(params_for_state(state, experimental_method=protocol))

    # eCLIP puts the crosslink on read 2; every other protocol on read 1. Never a hardcode.
    default_mate = "second" if protocol.lower() in ("eclip",) else "first"
    params["paired"] = args.paired or default_mate

    layouts = {s.strip().upper() for s in args.layouts.split(",") if s.strip()}
    if layouts:
        verdict = check_paired_selection(params["paired"], layouts=layouts)
        if not verdict.ok:
            raise CheckFailed(verdict.reason)

    if args.umi_length:
        params["umi_length"] = str(args.umi_length)

    # The barcode confirmed at gate 1 is what the coherence check compares against, and on a
    # raw header it is also the source of `umi_header_format` (all-N of the barcode's length)
    # — params_for_state knows the header state but not this study's barcode. One run takes
    # one format, so barcodes of different lengths cannot both be right and the study must be
    # split rather than parameterised for the majority.
    barcodes_file = out / "barcodes.json"
    fives = sorted({str(v.get("five_prime", "")).strip()
                    for v in json.loads(barcodes_file.read_text()).values()
                    if str(v.get("five_prime", "")).strip()}) if barcodes_file.exists() else []
    if len({len(b) for b in fives}) > 1:
        raise CheckFailed(
            f"the confirmed barcodes have {len({len(b) for b in fives})} different lengths "
            f"({', '.join(fives)}) but one run takes one umi_header_format — split the study "
            f"by barcode length."
        )
    barcode = fives[0] if fives else ""
    if params.get("move_umi_to_header") == "true" and barcode and not params.get("umi_header_format"):
        from lib.pipeline_params import barcode_to_header_format

        params["umi_header_format"] = barcode_to_header_format(barcode)

    coherence = check_umi_params(params, barcode=barcode)
    if not coherence.ok:
        raise CheckFailed(coherence.reason)

    (out / "pipeline_params.json").write_text(json.dumps(params, indent=2) + "\n")

    if not args.accept_params:
        raise Gate(
            f"analysis parameters for {protocol or 'this study'} require approval. "
            f"Confirm the UMI length against the authors' own pipeline config; composition "
            f"cannot settle its final base.",
            release="--accept-params",
            artefact=str(out / "pipeline_params.json"),
        )

    st.set_study(out, params_confirmed=True)
    return {"lines": [f"{k} = {v}" for k, v in sorted(params.items())],
            "note": f"{protocol}/{state}"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
