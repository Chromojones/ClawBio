"""Tests for process polling and credentials."""

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.credentials import credentials_in_env, write_credentials_env
from lib.process_runner import wait_for_process


def test_write_credentials_env_mode(tmp_path):
    path = write_credentials_env(tmp_path, "user", "pass")
    assert path.exists()
    assert oct(path.stat().st_mode & 0o777) == oct(0o600)
    assert "FLOWBIO_USERNAME='user'" in path.read_text()


def test_wait_for_process_fast(tmp_path):
    log = tmp_path / "step.log"
    log.write_text("working\n")
    proc = subprocess.Popen(["sleep", "0.1"])
    rc = wait_for_process(proc, log, "test-step", poll_interval=1)
    assert rc == 0
