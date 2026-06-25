"""Flow.bio credential prompt and secure env file for generated scripts."""

from __future__ import annotations

import getpass
import os
import stat
from pathlib import Path


def credentials_in_env() -> bool:
    return bool(os.environ.get("FLOWBIO_USERNAME") and os.environ.get("FLOWBIO_PASSWORD"))


def prompt_flow_credentials() -> tuple[str, str]:
    """Interactive credential entry (first workflow step when env not set)."""
    print("\n=== Flow.bio credentials ===")
    print("Required for upload and analysis. Stored locally in output/.flow_credentials.env (mode 600).")
    username = input("Flow username: ").strip()
    if not username:
        raise SystemExit("Flow username is required.")
    password = getpass.getpass("Flow password: ")
    if not password:
        raise SystemExit("Flow password is required.")
    return username, password


def write_credentials_env(output_dir: Path, username: str, password: str) -> Path:
    path = output_dir / ".flow_credentials.env"
    output_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"export FLOWBIO_USERNAME={username!r}\nexport FLOWBIO_PASSWORD={password!r}\n",
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def ensure_flow_credentials(
    output_dir: Path,
    *,
    prompt: bool = True,
) -> Path:
    """
    Load credentials from environment or prompt, then write .flow_credentials.env.
    Returns path to env file for sourcing in shell scripts.
    """
    username = os.environ.get("FLOWBIO_USERNAME", "")
    password = os.environ.get("FLOWBIO_PASSWORD", "")

    if not (username and password):
        if not prompt:
            raise SystemExit(
                "Flow credentials missing. Set FLOWBIO_USERNAME/FLOWBIO_PASSWORD or run without --skip-credential-prompt."
            )
        username, password = prompt_flow_credentials()
        os.environ["FLOWBIO_USERNAME"] = username
        os.environ["FLOWBIO_PASSWORD"] = password

    return write_credentials_env(output_dir, username, password)


def env_file_source_line(env_path: Path) -> str:
    return f'source "{env_path.resolve()}"'
