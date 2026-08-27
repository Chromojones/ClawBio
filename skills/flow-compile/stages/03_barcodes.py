#!/usr/bin/env python3
"""Stage 03 — the 5' barcode of every sample. HARD STOP.

Barcodes are never inferred and accepted in the same breath. A proposed barcode is evidence
awaiting a decision, and this stage exits 3 with the evidence written out; supplying the
confirmed file is the decision. That is why the gate is a separate exit code from a failed
check: nothing here is wrong, it is waiting on a person.

The evidence is per-position base composition over sampled reads. A fixed base sits far from
even (roughly 75% deviation); a randomer sits near it (roughly 4%). What composition cannot
settle is the UMI's last base: on GSE131210 position 13 measured 7.9% off even, between random
and genomic, because it is the terminal N of a synthesized oligo. So the layout is reported as
a RANGE and the length comes from the authors' own pipeline config, never from this stage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.read_structure import infer_inline_layout  # noqa: E402
from stages._common import Gate, parser_for, run_stage  # noqa: E402

NAME = "03_barcodes"
REQUIRES = ("02_index",)
OUTPUTS = ("barcodes.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--compositions", type=Path,
                        help="JSON of {sample: [per-position deviation, ...]} from sampled reads.")
    parser.add_argument("--accept-proposals", type=Path,
                        help="Confirmed barcode_proposals.json. Supplying it IS the approval.")
    return parser


def _inputs(args, out):
    return [p for p in (args.compositions, args.accept_proposals) if p]


def body(args, out: Path) -> dict:
    proposals_path = out / "barcode_proposals.json"

    if args.accept_proposals:
        confirmed = json.loads(Path(args.accept_proposals).read_text())
        (out / "barcodes.json").write_text(json.dumps(confirmed, indent=2) + "\n")
        return {
            "lines": [f"barcodes confirmed for {len(confirmed)} sample(s)"],
            "note": f"{len(confirmed)} confirmed",
        }

    if not args.compositions or not args.compositions.exists():
        raise Gate(
            "no barcode evidence yet. Sample reads and pass --compositions, or supply a "
            "confirmed --accept-proposals file.",
            release="--compositions <file> (then --accept-proposals)",
        )

    compositions = json.loads(args.compositions.read_text())
    proposals = {}
    for sample, deviations in compositions.items():
        layout = infer_inline_layout(deviations)
        proposals[sample] = {
            "barcode_len": layout.barcode_len,
            "barcode_certain": layout.barcode_certain,
            # A range, not a number. `umi_certain` false means composition could not settle
            # the last base and the study's own pipeline config must.
            "umi_len_min": layout.umi_len_min,
            "umi_len_max": layout.umi_len_max,
            "umi_certain": layout.umi_certain,
            "ambiguous_positions": layout.ambiguous_positions,
            "evidence": layout.describe(),
        }
    proposals_path.write_text(json.dumps(proposals, indent=2) + "\n")

    raise Gate(
        f"{len(proposals)} barcode proposal(s) require approval before any upload. "
        f"The UMI length is a RANGE: confirm it against the authors' pipeline config, "
        f"not against composition alone.",
        release=f"--accept-proposals {proposals_path.name}",
        artefact=str(proposals_path),
    )


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
