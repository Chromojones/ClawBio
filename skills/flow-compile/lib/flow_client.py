"""Every HTTP call the skill makes to Flow, and the helpers that read its responses.

Story: FAILURES.md#flow-client
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

#: The one definition. `credentials` imports it from here.
API_BASE = os.environ.get("FLOWBIO_API_BASE", "https://app.flow.bio/api").rstrip("/")

USER_AGENT = "flow-compile/1.0"


def project_id_of(sample: dict[str, Any] | None) -> str:
    """The owning project id, whether the API nested it (`GET /samples/{id}`) or not (listings).
    Compared as strings: ids exceed 2^53.
    """
    project = (sample or {}).get("project")
    if isinstance(project, dict):
        project = project.get("id")
    return "" if project is None else str(project)


def http_get(url: str, *, byte_range: int | None = None, timeout: int = 60) -> bytes:
    """GET with an optional byte range; an HTTP error names the URL."""
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
    """The route that serves a data file's bytes: under `/api/`, keyed by Data id, with the filename
    quoted so a separator cannot escape the route.
    """
    root = (base or API_BASE).rstrip("/")
    return f"{root}/downloads/{data_id}/{urllib.parse.quote(str(filename), safe='')}"


def resolve_token(explicit: str = "") -> str:
    """A Flow token: explicit, then `FLOW_API_TOKEN` (flowbio CLI), then `FLOW_TOKEN` (flow-bio
    skill), then `~/.config/flow/api-token`.
    """
    if explicit:
        return explicit.strip()
    env = (os.environ.get("FLOW_API_TOKEN", "").strip()
           or os.environ.get("FLOW_TOKEN", "").strip())
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
    """Exchange username/password for a token via `POST /login`, so later stages need no prompt.
    Returns "" on failure.
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

    def paginate(self, path: str, *, items_key: str, per_page: int = 100) -> list[dict]:
        """Every item behind a paginated listing, or an error — never a subset.

        The envelope's `count` is the total, not the page size, so a short read looks complete; a
        partial listing would make the dedup pre-flight report a clean import.

        Story: FAILURES.md#listing-pagination
        """
        collected: list[dict] = []
        total, page = None, 1
        while True:
            joiner = "&" if "?" in path else "?"
            payload = self.request(f"{path}{joiner}count={per_page}&page={page}")
            items = payload.get(items_key) or []
            collected += items
            if total is None:
                total = int(payload.get("count") or 0)
            if len(collected) >= total or not items:
                break
            page += 1
        if len(collected) != total:
            raise RuntimeError(
                f"{path} returned {len(collected)} of {total} {items_key} across {page} "
                f"page(s). A partial listing reads as a complete one — re-run rather than "
                f"acting on this."
            )
        return collected

    def project_samples(self, project_id: str) -> list[dict]:
        """Every sample in a project. Trimmed shape: names yes, `metadata` empty."""
        return self.paginate(f"/projects/{project_id}/samples", items_key="samples")

    def get_sample(self, sample_id: str) -> dict[str, Any]:
        return self.request(f"/samples/{sample_id}")

    def delete_sample(self, sample_id: str) -> None:
        """`POST /samples/{id}/delete`, accepted only when the sample then re-reads as 404.

        Never the `DELETE` verb, which returns 200 whether or not it deleted anything. Any other
        outcome raises.

        Story: FAILURES.md#sample-delete
        """
        self.request(f"/samples/{sample_id}/delete", {})
        try:
            self.request(f"/samples/{sample_id}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return
            raise RuntimeError(
                f"sample {sample_id}: re-read after delete returned HTTP {exc.code}, which "
                f"does not show the sample is gone. Check it directly before assuming so."
            ) from exc
        raise RuntimeError(
            f"sample {sample_id} still re-reads after POST /samples/{sample_id}/delete "
            f"reported success — it was not deleted."
        )

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        """`POST /projects/new` with `{name, description}`; returns the project once it re-reads with the
        requested name, since some Flow writes return 200 without taking effect.
        """
        created = self.request("/projects/new", {"name": name, "description": description})
        project_id = str(created.get("id") or "")
        if not project_id:
            raise RuntimeError(
                f"POST /projects/new returned no id ({created!r}); nothing was created."
            )
        live = self.request(f"/projects/{project_id}")
        if live.get("name") != name:
            raise RuntimeError(
                f"created project {project_id} re-reads as {live.get('name')!r}, "
                f"not {name!r} — do not trust this creation."
            )
        return live

    def edit_sample(self, sample_id: str, body: dict[str, str]) -> dict[str, Any]:
        return self.request(f"/samples/{sample_id}/edit", body)

    def project_executions(self, project_id: str) -> dict[str, Any]:
        return self.request(f"/projects/{project_id}/executions")

    def search(self, query: str) -> dict[str, Any]:
        return self.request(f"/search?q={urllib.parse.quote(str(query))}")
