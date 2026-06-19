"""Run long-lived steps with periodic status polling."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

DEFAULT_POLL_INTERVAL_SEC = 240  # 4 minutes


def _tail_log_line(log_path: Path, max_len: int = 120) -> str:
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    return lines[-1][:max_len]


def wait_for_process(
    proc: subprocess.Popen,
    log_path: Path,
    step_name: str,
    *,
    poll_interval: int = DEFAULT_POLL_INTERVAL_SEC,
) -> int:
    """Poll every poll_interval seconds until process exits; print status to stdout."""
    start = time.monotonic()
    while True:
        rc = proc.poll()
        if rc is not None:
            elapsed_min = (time.monotonic() - start) / 60
            print(f"✓ {step_name} finished (exit {rc}, {elapsed_min:.1f} min) → {log_path}")
            return rc

        elapsed_min = (time.monotonic() - start) / 60
        latest = _tail_log_line(log_path)
        print(f"… {step_name} still running ({elapsed_min:.1f} min, check again in {poll_interval // 60} min)")
        print(f"  log: {log_path}")
        if latest:
            print(f"  latest: {latest}")
        time.sleep(poll_interval)


def run_shell_step(
    step_name: str,
    script_path: Path,
    log_path: Path,
    *,
    poll_interval: int = DEFAULT_POLL_INTERVAL_SEC,
    extra_env: dict[str, str] | None = None,
) -> int:
    """Run a bash script in background, poll until complete."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = None
    if extra_env:
        import os

        env = os.environ.copy()
        env.update(extra_env)

    print(f"→ Starting {step_name}: {script_path}")
    with log_path.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            ["bash", str(script_path)],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
        )
    return wait_for_process(proc, log_path, step_name, poll_interval=poll_interval)
