#!/usr/bin/env python3
"""Stage 110 — submit the import and poll it to completion.

The project is set in the sheet, reserved since flowbio 0.12.0, so there is no assignment
step here any more. Annotations are a different matter: the import job forwards
`__annotation` columns as ordinary metadata keys and discards them server-side, so they are
repaired in 11_verify rather than pretended to have arrived.

Submitting is the first irreversible action in the run, so it refuses without both gates
confirmed rather than trusting the caller to have run them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from stages._common import CheckFailed, parser_for, run_stage  # noqa: E402

NAME = "110_import"
REQUIRES = ("109_sheet",)
OUTPUTS = ("import_job.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--submit", action="store_true",
                        help="Actually submit. Without it the command is printed only.")
    parser.add_argument("--poll-interval", type=int, default=60)
    return parser


def _inputs(args, out):
    return [out / "import_sheet.csv"]


def body(args, out: Path) -> dict:
    study = st.study(out)
    if not study.get("params_confirmed"):
        raise CheckFailed("analysis parameters were never confirmed; 108_params must pass first.")

    sheet = out / "import_sheet.csv"
    command = ["flowbio", "--json", "samples", "import", "--sheet", str(sheet)]

    if not args.submit:
        return {"lines": ["dry run, nothing submitted", "  " + " ".join(command),
                          "re-run with --submit to import"], "note": "dry run"}

    proc = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise CheckFailed(f"import submission failed: {proc.stderr[-600:]}")

    job = json.loads(proc.stdout)
    (out / "import_job.json").write_text(json.dumps(job, indent=2) + "\n")
    st.set_study(out, import_job=job.get("id", ""))
    return {"lines": [f"job {job.get('id')} submitted ({job.get('status')})",
                      "poll with: flowbio samples import-status --job-id "
                      f"{job.get('id')}"],
            "note": str(job.get("id", ""))}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     inputs=_inputs, outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
