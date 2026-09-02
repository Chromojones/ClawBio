#!/usr/bin/env python3
"""Flow Compile — drive the CLIP upload stages in order.

This used to be 1,026 lines with every stage body inside one function, and that function's
control flow was the dependency graph. The bodies now live in `stages/`, numbered in running
order, and what is left here is the part that could not move: which stage comes next, and
which line this run is on.

The stage model has one real cost — sixteen scripts is easy to lose your place in — so the
driver answers "where am I" from `state.json` rather than from memory:

    python3 flow_compile.py --status --output <dir>     what has run, and what is waiting
    python3 flow_compile.py --next   --output <dir>     the command to run next
    python3 flow_compile.py --run    --output <dir> ... run stages until one stops

A gate is not a failure. `--next` re-offers a gated stage rather than stepping past it,
because the run is paused on a person, not broken. Stages whose required flags only the
operator can supply (evidence files, maps) are printed with placeholders rather than run:
`--run` resumes a configured run; it does not replace running those stages by hand.

See `reference/stages.md` for what each stage decides.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402

STAGES_DIR = SKILL_DIR / "stages"

#: Every study. 03 and 05 are hard stops.
TRUNK = (
    "00_setup", "01_study", "02_index", "03_barcodes",
    "04_annotate", "05_metadata", "06_route",
)

#: SRA-direct. 108 is the third hard stop and sits on both lines.
DIRECT_LINE = ("101_preview", "108_params", "109_sheet", "110_import")

#: Local, for a study absent from SRA/ENA.
LOCAL_LINE = ("201_fetch", "108_params", "210_upload")

#: Shared tail. 12 is the fourth hard stop.
DELIVERY = ("11_verify", "12_analysis", "13_audit")

_LINES = {"direct": DIRECT_LINE, "local": LOCAL_LINE}


def planned_stages(output_dir) -> list[str]:
    """The stages this run will take, as far as the route is known.

    Before 06_route there is no line, so only the trunk is planned. Guessing one would put a
    stage in the list that this study may never run.
    """
    try:
        line = st.load(output_dir)["route"].get("line", "")
    except st.StateError:
        line = ""
    if not line:
        return list(TRUNK)
    return [*TRUNK, *_LINES.get(line, ()), *DELIVERY]


def next_stage(output_dir) -> str | None:
    """The first stage that has not completed. A gated stage is re-offered, not skipped."""
    doc = st.load(output_dir)
    for name in planned_stages(output_dir):
        if doc["stages"].get(name, {}).get("status") != st.OK:
            return name
    return None


def command_for(name: str, output_dir) -> list[str]:
    return [sys.executable, str(STAGES_DIR / f"{name}.py"), "--output", str(output_dir)]


def required_flags(name: str) -> list[tuple[str, str]]:
    """The stage's own required flags beyond --output, read from its parser.

    `--next` used to print commands that exited 2: stages 02, 03, 04, 11 and 13 take
    required flags whose values only the operator knows, and a printed command that dies on
    argparse reads as the thing to run. Asking each stage's parser keeps this list from
    drifting the way a table here would.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"stage_{name}", STAGES_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [(action.option_strings[0], action.dest)
            for action in module.build_parser()._actions
            if action.required and action.option_strings
            and "--output" not in action.option_strings]


def print_status(output_dir) -> int:
    try:
        doc = st.load(output_dir)
    except st.StateError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    stages = doc["stages"]
    route = doc.get("route", {})
    if route.get("line"):
        print(f"route: {route['line']} ({route.get('protocol') or 'protocol unknown'}) "
              f"— {route.get('reason', '')}")
    else:
        print("route: not yet decided (06_route)")
    print()

    for name in planned_stages(output_dir):
        entry = stages.get(name, {})
        status = entry.get("status", "")
        if status == st.OK:
            mark, detail = "  ok  ", entry.get("note", "")
        elif status == st.GATED:
            mark = " wait "
            detail = f"awaiting approval — re-run with {entry.get('release', '?')}"
        elif status == st.FAILED:
            mark, detail = "failed", entry.get("note", "")
        else:
            mark, detail = "  --  ", ""
        print(f"  [{mark}] {name:<14} {detail}")

    upcoming = next_stage(output_dir)
    print()
    print(f"next: {upcoming}" if upcoming else "next: nothing — the run is complete")
    return 0


def print_next(output_dir) -> int:
    name = next_stage(output_dir)
    if not name:
        print("nothing to run — every planned stage is complete")
        return 0
    entry = st.load(output_dir)["stages"].get(name, {})
    if entry.get("status") == st.GATED:
        print(f"{name} is waiting on approval. Review its artefact, then:")
        print("  " + " ".join(command_for(name, output_dir)) + f" {entry.get('release', '')}")
        return 0
    placeholders = [f"{flag} <{dest}>" for flag, dest in required_flags(name)]
    print(" ".join([*command_for(name, output_dir), *placeholders]))
    if placeholders:
        print(f"# fill in the <value>s; see {name}.py --help and reference/stages.md")
    return 0


def run_through(output_dir, *, stop_after: str = "") -> int:
    """Run stages in order until one does not return 0. Gates stop the run by design."""
    while True:
        name = next_stage(output_dir)
        if not name:
            print("every planned stage is complete")
            return 0
        # Stop BEFORE a stage whose required flags this driver cannot supply, naming them,
        # rather than invoking it and surfacing an argparse usage error mid-run.
        missing = required_flags(name)
        if missing:
            print(f"\n{name} needs flags only you can supply — run it by hand:")
            print("  " + " ".join([*command_for(name, output_dir),
                                   *(f"{flag} <{dest}>" for flag, dest in missing)]))
            print(f"then resume with `flow_compile.py --run --output {output_dir}`.")
            return 2
        print(f"\n=== {name} ===")
        code = subprocess.run(command_for(name, output_dir)).returncode
        if code != 0:
            print(f"\n{name} stopped with exit {code}. "
                  f"Run `flow_compile.py --status --output {output_dir}` for where to resume.")
            return code
        if stop_after and name == stop_after:
            return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="flow_compile.py",
        description="Drive the CLIP upload stages. See reference/stages.md.",
    )
    parser.add_argument("--output", required=True, type=Path, help="The run directory.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true", help="What has run, and what waits.")
    action.add_argument("--next", action="store_true", help="Print the next command.")
    action.add_argument("--run", action="store_true", help="Run stages until one stops.")
    action.add_argument("--list-stages", action="store_true", help="The full stage model.")
    parser.add_argument("--through", default="", help="With --run, stop after this stage.")
    args = parser.parse_args(argv)

    if args.list_stages:
        for label, names in (("trunk", TRUNK), ("direct", DIRECT_LINE),
                             ("local", LOCAL_LINE), ("delivery", DELIVERY)):
            print(f"{label:<9} {' -> '.join(names)}")
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    if args.status:
        return print_status(args.output)
    if args.next:
        return print_next(args.output)
    return run_through(args.output, stop_after=args.through)


if __name__ == "__main__":
    raise SystemExit(main())
