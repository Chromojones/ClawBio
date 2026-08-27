#!/usr/bin/env python3
"""Stage 06 — SRA-direct or local, and which protocol. The branch.

The routing rule is one condition, and it took two separate findings to get there.

Historically the local line existed for four reasons: FLASH and uvCLAP read handling, a UMI
sitting in the header comment, and a study simply absent from SRA. The first two are gone with
those protocols removed. The third goes once `removespace` runs inside the clip-seq pipeline
and stops turning a header comment into a constant final field. What is left is:

    study not in SRA/ENA  -> local
    otherwise             -> direct

So SRA-direct is the path for essentially every study, which is what SKILL.md always claimed
and was never true before.

The protocol is recorded here too, because both lines need it and neither should re-derive it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from lib.protocol import detect_method, is_supported  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "06_route"
REQUIRES = ("05_metadata",)
OUTPUTS = ("state.json",)

DIRECT, LOCAL = "direct", "local"


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--not-in-sra", action="store_true",
                        help="The study has no SRA/ENA accessions. Forces the local line.")
    parser.add_argument("--force-local", action="store_true",
                        help="Take the local line anyway, recording why.")
    parser.add_argument("--reason", default="", help="Why, when forcing.")
    return parser


def _inputs(args, out):
    return [out / "annotation.raw.csv"]


def body(args, out: Path) -> dict:
    import pandas as pd

    annotation = pd.read_csv(out / "annotation.raw.csv", dtype=str).fillna("")
    study = st.study(out)

    methods = sorted({m for m in annotation.get("Experimental Method", []) if str(m).strip()})
    protocol = methods[0] if len(methods) == 1 else (
        detect_method("", study.get("title", "")) if not methods else "")

    if len(methods) > 1:
        raise CheckFailed(
            f"the study mixes protocols {methods}. Parameters differ per protocol, so split "
            f"it into one run per protocol rather than parameterising the majority."
        )
    if protocol and not is_supported(protocol):
        raise CheckFailed(
            f"{protocol} is detected but not processed by this skill. Naming it and refusing "
            f"is deliberate: falling through to the iCLIP default would mislabel it."
        )

    if args.not_in_sra or args.force_local:
        line = LOCAL
        reason = args.reason or ("no SRA/ENA accessions" if args.not_in_sra else "forced")
    else:
        line = DIRECT
        reason = "accessions resolve in SRA/ENA"

    st.set_route(out, line=line, protocol=protocol, reason=reason)
    return {
        "lines": [f"protocol: {protocol or 'unknown'}",
                  f"line: {line} ({reason})",
                  f"next: stages/{'101_preview.py' if line == DIRECT else '201_fetch.py'}"],
        "note": f"{line}/{protocol}",
    }


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
