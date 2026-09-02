"""00_setup must defuse the FLOW_* / FLOWBIO_* name trap instead of walking into it.

This skill reads ``FLOWBIO_USERNAME`` / ``FLOWBIO_PASSWORD`` (the vendored Flow scripts'
names); the sibling ``flow-bio`` skill and the root CLAUDE.md use ``FLOW_USERNAME`` /
``FLOW_PASSWORD`` / ``FLOW_TOKEN``. An agent arriving from either sets the FLOW_* names,
00_setup found nothing, and the run proceeded credential-less to fail at the first network
stage. ``FLOW_TOKEN`` is now honoured by ``resolve_token``; a FLOW_*-only username still
cannot be silently adopted (later stages spawn fresh processes that read FLOWBIO_*), so the
stage names the mismatch out loud instead.
"""

import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

PY = sys.executable

_CLEARED = ("FLOWBIO_USERNAME", "FLOWBIO_PASSWORD", "FLOW_API_TOKEN", "FLOW_TOKEN",
            "FLOW_USERNAME", "FLOW_PASSWORD")


def _setup(out, env_extra, *extra):
    env = {k: v for k, v in os.environ.items() if k not in _CLEARED}
    env["FLOW_TOKEN_FILE"] = str(out / "no-such-token-file")
    env.update(env_extra)
    return subprocess.run(
        [PY, str(SKILL_DIR / "stages" / "00_setup.py"), "--output", str(out), *extra],
        capture_output=True, text=True, cwd=str(SKILL_DIR), timeout=90, env=env,
    )


class TestTheEnvVarTrap:
    def test_flow_token_counts_as_credentials(self, tmp_path):
        proc = _setup(tmp_path, {"FLOW_TOKEN": "tok"})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "token available" in proc.stdout

    def test_flow_username_alone_is_named_as_the_wrong_name(self, tmp_path):
        proc = _setup(tmp_path, {"FLOW_USERNAME": "user", "FLOW_PASSWORD": "pw"})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "FLOW_USERNAME" in proc.stdout and "FLOWBIO_USERNAME" in proc.stdout

    def test_no_credentials_at_all_stays_the_plain_warning(self, tmp_path):
        proc = _setup(tmp_path, {})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "credentials: NONE" in proc.stdout
        assert "FLOW_USERNAME" not in proc.stdout
