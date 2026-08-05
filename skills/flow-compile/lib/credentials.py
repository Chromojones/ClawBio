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


API_BASE = os.environ.get("FLOWBIO_API_BASE", "https://app.flow.bio/api").rstrip("/")


def mint_api_token(username: str, password: str, *, base: str = API_BASE) -> str:
    """Exchange username/password for an API token via POST /login.

    The vendored upload/analysis scripts authenticate with username+password, but the
    flowbio CLI (`samples import`, `import-status`) wants a **token** — `FLOW_API_TOKEN`,
    `--token-file`, or `~/.config/flow/api-token`. Minting one here means the SRA-direct
    path never has to prompt again mid-workflow.

    Returns "" if the exchange fails; callers fall back to username/password auth.
    """
    import json
    import urllib.request

    try:
        request = urllib.request.Request(
            f"{base}/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return str(json.loads(response.read()).get("token") or "")
    except Exception:  # noqa: BLE001 - offline or bad credentials is not fatal here
        return ""


def write_credentials_env(
    output_dir: Path, username: str, password: str, token: str = ""
) -> Path:
    path = output_dir / ".flow_credentials.env"
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"export FLOWBIO_USERNAME={username!r}",
        f"export FLOWBIO_PASSWORD={password!r}",
    ]
    if token:
        # Consumed by `flowbio samples import` and lib/flow_project_assign.py.
        lines.append(f"export FLOW_API_TOKEN={token!r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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

    token = os.environ.get("FLOW_API_TOKEN", "") or mint_api_token(username, password)
    if token:
        os.environ["FLOW_API_TOKEN"] = token

    return write_credentials_env(output_dir, username, password, token)


def env_file_source_line(env_path: Path) -> str:
    return f'source "{env_path.resolve()}"'
