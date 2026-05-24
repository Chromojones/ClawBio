"""Programmatic entry point for gi-annotation.

Invokes the skill's CLI in a subprocess (matching how clawbio.py runs
skills) and returns the parsed result.json. This avoids relying on
private helper functions inside gi_annotation.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_SKILL_DIR = Path(__file__).resolve().parent
_SCRIPT = _SKILL_DIR / "gi_annotation.py"


def run(input_path: str, output_dir: str = "/tmp/gi-annotation") -> dict:
    """Run the skill programmatically. Returns the parsed result.json dict.

    Raises RuntimeError if the skill exits non-zero.
    """
    out = Path(output_dir)
    cmd = [sys.executable, str(_SCRIPT), "--input", str(input_path), "--output", str(out)]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"gi-annotation exited with code {completed.returncode}: {completed.stderr.strip()}"
        )
    result_json = out / "result.json"
    if not result_json.exists():
        raise RuntimeError(f"gi-annotation produced no result.json at {result_json}")
    return json.loads(result_json.read_text())
