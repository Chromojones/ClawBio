"""Every HTTP call the skill makes, and one answer to "which project is this sample in?".

Network access was written where it was first needed: ``_http_get`` twice (one copy had Range
support, the other had HTTPError wrapping, neither had both), ``API_BASE`` twice outside
``lib/vendor/``, and ``RestFlowApi`` inside a module about project assignment.

``project_id_of`` existed three times because the API returns the field two ways — nested from
``GET /samples/{id}``, bare from listings. The third copy handled only the nested shape and
raised ``AttributeError`` on the other, in the repair stage, whose input is a listing.

Story: FAILURES.md#flow-client
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

#: The one definition. `credentials` and `flow_project_assign` import it from here.
API_BASE = os.environ.get("FLOWBIO_API_BASE", "https://app.flow.bio/api").rstrip("/")

USER_AGENT = "flow-compile/1.0"


def project_id_of(sample: dict[str, Any] | None) -> str:
    """The owning project id, whichever shape the API used.

    ``GET /samples/{id}`` nests it (``{"project": {"id": "P1"}}``); listings return it bare
    (``{"project": "P1"}``). Ids exceed 2^53 and are compared as strings everywhere.
    """
    project = (sample or {}).get("project")
    if isinstance(project, dict):
        project = project.get("id")
    return "" if project is None else str(project)


def http_get(url: str, *, byte_range: int | None = None, timeout: int = 60) -> bytes:
    """GET, with the Range support and the error wrapping that were in separate copies."""
    headers = {"User-Agent": USER_AGENT}
    if byte_range:
        headers["Range"] = f"bytes=0-{byte_range}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc


def download_url(data_id: str, filename: str, *, base: str = "") -> str:
    """The route that serves a data file's bytes.

    Found by trial, so it is pinned by test: it sits under ``/api/`` unlike the app-level URLs,
    and it takes a **Data** id despite the ``downloads`` prefix. The filename is quoted with no
    safe characters, so a path separator inside it cannot walk out of the route.
    """
    root = (base or API_BASE).rstrip("/")
    return f"{root}/downloads/{data_id}/{urllib.parse.quote(str(filename), safe='')}"


def resolve_token(explicit: str = "") -> str:
    """``--token`` → ``FLOW_API_TOKEN`` → ``~/.config/flow/api-token``, as the flowbio CLI does."""
    if explicit:
        return explicit.strip()
    env = os.environ.get("FLOW_API_TOKEN", "").strip()
    if env:
        return env
    token_file = os.environ.get("FLOW_TOKEN_FILE") or os.path.expanduser(
        "~/.config/flow/api-token"
    )
    try:
        with open(token_file, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def mint_api_token(username: str, password: str, *, base: str = "") -> str:
    """Exchange username/password for a token via ``POST /login``.

    The vendored upload and analysis scripts authenticate with username+password, but the
    flowbio CLI wants a token. Minting one up front means the SRA-direct path never prompts
    again mid-run. Returns ``""`` on failure; callers fall back to username/password auth.
    """
    root = (base or API_BASE).rstrip("/")
    try:
        request = urllib.request.Request(
            f"{root}/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return str(json.loads(response.read()).get("token") or "")
    except Exception:  # noqa: BLE001 - offline or bad credentials is not fatal here
        return ""


class FlowClient:
    """Token-authenticated REST client for the calls this skill makes."""

    def __init__(self, token: str, base: str = "") -> None:
        self.token = token
        self.base = (base or API_BASE).rstrip("/")

    def request(self, path: str, body: dict | None = None, *, timeout: int = 90) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())

    # Kept for the shim in flow_project_assign.
    _request = request

    def get_sample(self, sample_id: str) -> dict[str, Any]:
        return self.request(f"/samples/{sample_id}")

    def edit_sample(self, sample_id: str, body: dict[str, str]) -> dict[str, Any]:
        return self.request(f"/samples/{sample_id}/edit", body)

    def project_executions(self, project_id: str) -> dict[str, Any]:
        return self.request(f"/projects/{project_id}/executions")

    def search(self, query: str) -> dict[str, Any]:
        return self.request(f"/search?q={urllib.parse.quote(str(query))}")
