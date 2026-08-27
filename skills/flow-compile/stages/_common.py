"""The contract every stage keeps, so that seventeen scripts behave like one command.

Splitting the orchestrator into stages only pays off if a reader can predict, without opening
any of them, how a stage takes its arguments, where it writes, what its exit code means, and
what happens when it is run twice. All of that lives here; a stage supplies a name, its
prerequisites, its outputs, and a body.

Exit codes are the interface:

===  ==========================================================================
0    ok
2    usage error — the arguments are wrong
3    gate — a human artefact is required before continuing (not a failure)
4    check failed — the data is wrong
5    prerequisite stage not ok — run that stage first
===  ==========================================================================

3 versus 4 is the distinction the old orchestrator could not express. A barcode awaiting
approval and a barcode that contradicts the reads both printed a warning and continued.

Story: FAILURES.md#stage-contract
"""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402
from lib.results import blocking, render_findings  # noqa: E402

OK, USAGE, GATE, CHECK_FAILED, PREREQUISITE = 0, 2, 3, 4, 5

#: Declared as a module constant so the contract test can read a stage's prerequisites without
#: importing it (importing every stage would run their import side effects).
_REQUIRES_RE = re.compile(r"^REQUIRES\s*=\s*\(([^)]*)\)", re.M)


def prerequisites_of(stage_path) -> list[str]:
    """The stages a stage declares it depends on, read from its source."""
    match = _REQUIRES_RE.search(Path(stage_path).read_text())
    if not match:
        return []
    return [s.strip().strip("\"'") for s in match.group(1).split(",") if s.strip().strip("\"'")]


class Gate(Exception):
    """A human artefact is required. Not a failure: the run is paused, not wrong."""

    def __init__(self, message: str, *, release: str = "", artefact: str = "") -> None:
        super().__init__(message)
        self.release = release
        self.artefact = artefact


class CheckFailed(Exception):
    """The data is wrong. Distinct from Gate, which is waiting on a person."""

    def __init__(self, message: str, findings: Sequence | None = None) -> None:
        super().__init__(message)
        self.findings = list(findings or [])


def parser_for(name: str, description: str) -> argparse.ArgumentParser:
    """A stage's parser, pre-loaded with the arguments every stage takes."""
    parser = argparse.ArgumentParser(prog=name, description=description)
    parser.add_argument("--output", required=True, type=Path,
                        help="Run directory. Holds state.json and every artefact.")
    parser.add_argument("--force", action="store_true",
                        help="Recompute even if this stage's inputs are unchanged.")
    parser.add_argument("--json", action="store_true", help="Machine-readable result on stdout.")
    return parser


def _output_from(argv: Sequence[str]) -> Path | None:
    """Find --output without a full parse, so prerequisites can be checked first."""
    argv = list(argv)
    for i, token in enumerate(argv):
        if token == "--output" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if token.startswith("--output="):
            return Path(token.split("=", 1)[1])
    return None


def run_stage(
    name: str,
    body: Callable[[argparse.Namespace, Path], dict | None],
    *,
    parser: argparse.ArgumentParser,
    requires: Sequence[str] = (),
    inputs: Callable[[argparse.Namespace, Path], list] | None = None,
    outputs: Sequence[str] = (),
    argv: Sequence[str] | None = None,
) -> int:
    """Run one stage's body inside the contract. Returns the process exit code.

    The body is called only when the work is actually needed: prerequisites are checked first,
    then the inputs digest, so re-running a completed stage costs nothing and re-running an
    invalidated one recomputes. That is what removes the "run the command three times" loop —
    a stage no longer has to be re-executed for a later one to see its output.
    """
    raw = list(sys.argv[1:] if argv is None else argv)

    # Prerequisites are checked BEFORE argparse validates the rest, so a stage run out of order
    # says "run 01_study first" rather than "--geo-matrix is required". When both are wrong the
    # ordering one is the more useful thing to hear, and fixing the flags first would only
    # surface the real problem on the next attempt.
    out = _output_from(raw)
    if out is None:
        parser.parse_args(raw)          # let argparse report the missing --output and exit 2
        return USAGE                     # unreachable; argparse raises SystemExit(2)

    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"{name}: cannot create {out}: {exc}", file=sys.stderr)
        return USAGE

    try:
        st.require(out, *requires)
    except st.PrerequisiteError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return PREREQUISITE
    except st.StateError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return USAGE

    args = parser.parse_args(raw)

    declared = list(inputs(args, out)) if inputs else []
    cli = [a for a in raw if a not in ("--force", "--json")]

    if not st.begin(out, name, inputs=declared, args=cli, force=args.force):
        print(f"{name}: already done (inputs unchanged) — pass --force to recompute")
        return OK

    try:
        result = body(args, out) or {}
    except Gate as exc:
        st.record(out, name, st.GATED, release=exc.release, note=str(exc))
        print(f"\n{name}: {exc}")
        if exc.artefact:
            print(f"  review:  {exc.artefact}")
        if exc.release:
            print(f"  release: re-run with {exc.release}")
        return GATE
    except CheckFailed as exc:
        st.record(out, name, st.FAILED, note=str(exc),
                  findings=[f.describe() for f in exc.findings])
        print(f"\n{name}: {exc}", file=sys.stderr)
        if exc.findings:
            print(render_findings(exc.findings, title=name, total=len(exc.findings)),
                  file=sys.stderr)
        return CHECK_FAILED
    except KeyboardInterrupt:
        print(f"\n{name}: interrupted", file=sys.stderr)
        return USAGE
    except Exception as exc:  # noqa: BLE001 - a stage crash must not look like a clean failure
        st.record(out, name, st.FAILED, note=f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return CHECK_FAILED

    findings = result.get("findings") or []
    if blocking(findings):
        st.record(out, name, st.FAILED, findings=[f.describe() for f in findings])
        print(render_findings(findings, title=name, total=len(findings)), file=sys.stderr)
        return CHECK_FAILED

    st.record(out, name, st.OK, outputs=list(outputs), inputs=declared, args=cli,
              note=str(result.get("note", "")))
    if findings:
        print(render_findings(findings, title=name, total=len(findings)))
    for line in result.get("lines", []):
        print(line)
    return OK
