#!/usr/bin/env python3
"""Stage 00 — establish the run directory and the credentials everything else assumes.

First stage, so it has no prerequisites and is the only one that may run against a bare
directory. Its whole job is to make the next sixteen stages able to assume a `state.json`, an
output directory that exists, and either working credentials or an explicit record that the
run is offline.

Credentials are minted into a token here rather than at each network stage, because the
alternative is a prompt arriving in the middle of a long import.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import state as st  # noqa: E402
from stages._common import parser_for, run_stage  # noqa: E402

NAME = "00_setup"
REQUIRES = ()
OUTPUTS = ("state.json",)


def build_parser():
    parser = parser_for(NAME, __doc__.splitlines()[0])
    parser.add_argument("--accession", default="", help="GEO/ArrayExpress study accession.")
    parser.add_argument("--project-id", default="", help="Flow project id to import into.")
    parser.add_argument("--create-project", default="", metavar="NAME",
                        help="Create a new Flow project with this name and adopt its id. "
                             "The flag is the instruction; conflicts with --project-id.")
    parser.add_argument("--project-description", default="",
                        help="Description for --create-project.")
    parser.add_argument("--offline", action="store_true",
                        help="Record that no credentials are available and skip minting.")
    return parser


def body(args, out: Path) -> dict:
    from stages._common import CheckFailed

    lines = [f"run directory: {out}"]

    if args.create_project and args.project_id:
        raise CheckFailed(
            "--create-project and --project-id are two answers to the same question. "
            "Adopt the existing project, or create a new one, not both."
        )
    if args.create_project and args.offline:
        raise CheckFailed("--create-project needs the network; it cannot run with --offline.")

    token = ""
    if not args.offline:
        from lib.flow_client import mint_api_token, resolve_token
        import os

        token = resolve_token()
        if not token:
            username = os.environ.get("FLOWBIO_USERNAME", "")
            password = os.environ.get("FLOWBIO_PASSWORD", "")
            if username and password:
                token = mint_api_token(username, password)

    project_id = args.project_id
    if args.create_project:
        if not token:
            raise CheckFailed(
                "--create-project needs credentials and none resolved. Set "
                "FLOWBIO_USERNAME/FLOWBIO_PASSWORD or a FLOW_TOKEN."
            )
        from lib.flow_client import FlowClient

        project = FlowClient(token).create_project(
            args.create_project, args.project_description)
        project_id = str(project["id"])
        lines.append(f"project created: {args.create_project} -> "
                     f"https://app.flow.bio/projects/{project_id}/")

    st.set_study(out, accession=args.accession, project_id=project_id,
                 offline=bool(args.offline), authenticated=bool(token))

    if token:
        lines.append("credentials: token available")
    elif args.offline:
        lines.append("credentials: offline run, none minted")
    else:
        lines.append("credentials: NONE — network stages will fail. Set FLOWBIO_USERNAME and "
                     "FLOWBIO_PASSWORD, or pass --offline.")
        # The sibling flow-bio skill uses FLOW_USERNAME/FLOW_PASSWORD. Adopting them here
        # would lie: later stages spawn fresh processes (and vendored scripts) that read only
        # FLOWBIO_*. So the mismatch is named instead of silently walked into.
        import os

        if os.environ.get("FLOW_USERNAME") or os.environ.get("FLOW_PASSWORD"):
            lines.append("  note: FLOW_USERNAME/FLOW_PASSWORD are set, but those are the "
                         "flow-bio skill's names — this skill reads FLOWBIO_USERNAME/"
                         "FLOWBIO_PASSWORD (a FLOW_TOKEN, however, is honoured).")
    if args.accession:
        lines.append(f"study: {args.accession}")
    if project_id:
        lines.append(f"project: {project_id}")
    return {"lines": lines, "note": args.accession or "no accession"}


def main(argv=None) -> int:
    return run_stage(NAME, body, parser=build_parser(), requires=REQUIRES,
                     outputs=OUTPUTS, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
