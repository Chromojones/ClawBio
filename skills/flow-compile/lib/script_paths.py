"""Resolve bundled Flow API scripts (vendored under lib/vendor/flow_api/)."""

from __future__ import annotations

from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
_VENDOR = _SKILL_DIR / "lib" / "vendor" / "flow_api"


def resolve_flow_script(name: str, explicit: Path | None = None) -> Path | None:
    """
    Locate upload/analysis/preprocessing helpers.

    Search order: explicit path → skill vendor copy → advbfx flowAPIscripts → cwd.
    """
    if explicit and explicit.is_file():
        return explicit.resolve()
    for candidate in (
        _VENDOR / name,
        Path("/home/mikej10/advbfx/flowAPIscripts") / name,
        Path.cwd() / "flowAPIscripts" / name,
        Path.cwd().parent / "flowAPIscripts" / name,
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None
