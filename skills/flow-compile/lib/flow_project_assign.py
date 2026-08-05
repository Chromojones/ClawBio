"""Attach imported samples to a Flow project (the step `samples import` cannot do).

`flowbio samples import --sheet` accepts only ``accession``, ``name``, ``organism`` and
``sample_type`` as reserved columns — there is **no project field**. A ``project`` column
in the sheet is silently swallowed as metadata, so a successful import leaves every sample
unattached and invisible in the project view. This module performs the second step via
``POST /samples/{id}/edit`` with ``{"project": "<id>"}``.

The API surface is injected (`api` object with ``get_sample`` / ``edit_sample``) so the
planning and batching logic is unit-testable without network access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

API_BASE = os.environ.get("FLOWBIO_API_BASE", "https://app.flow.bio/api").rstrip("/")


class FlowApi(Protocol):
    def get_sample(self, sample_id: str) -> dict[str, Any]: ...
    def edit_sample(self, sample_id: str, body: dict[str, str]) -> dict[str, Any]: ...


@dataclass
class AssignmentStep:
    sample_id: str
    needs_change: bool
    current_project: str = ""


@dataclass
class AssignmentResult:
    planned: int = 0
    assigned: int = 0
    skipped: int = 0
    failed: int = 0
    failures: dict[str, str] = field(default_factory=dict)


def _project_id_of(sample: dict[str, Any]) -> str:
    project = (sample or {}).get("project")
    if isinstance(project, dict):
        return str(project.get("id") or "")
    return str(project or "")


def build_assignment_plan(
    api: FlowApi, sample_ids: list[str], project_id: str
) -> list[AssignmentStep]:
    """Decide, per sample, whether an edit is needed."""
    plan: list[AssignmentStep] = []
    for sample_id in sample_ids:
        sample_id = str(sample_id).strip()
        if not sample_id:
            continue
        try:
            current = _project_id_of(api.get_sample(sample_id))
        except Exception:  # noqa: BLE001 - unreadable sample still gets attempted
            current = ""
        plan.append(
            AssignmentStep(
                sample_id=sample_id,
                needs_change=current != str(project_id),
                current_project=current,
            )
        )
    return plan


def assign_samples_to_project(
    api: FlowApi,
    sample_ids: list[str],
    project_id: str,
    *,
    dry_run: bool = False,
) -> AssignmentResult:
    """Attach each sample to ``project_id``. One failure does not abort the batch."""
    project_id = str(project_id or "").strip()
    if not project_id:
        raise ValueError("a project id is required to assign samples")

    plan = build_assignment_plan(api, sample_ids, project_id)
    result = AssignmentResult(planned=sum(1 for step in plan if step.needs_change))

    for step in plan:
        if not step.needs_change:
            result.skipped += 1
            continue
        if dry_run:
            continue
        try:
            api.edit_sample(step.sample_id, {"project": project_id})
            result.assigned += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            result.failed += 1
            result.failures[step.sample_id] = str(exc)
    return result


# --------------------------------------------------------------------------- REST impl


class RestFlowApi:
    """Minimal token-authenticated REST client for the two calls we need."""

    def __init__(self, token: str, base: str = API_BASE) -> None:
        self.token = token
        self.base = base.rstrip("/")

    def _request(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read())

    def get_sample(self, sample_id: str) -> dict[str, Any]:
        return self._request(f"/samples/{sample_id}")

    def edit_sample(self, sample_id: str, body: dict[str, str]) -> dict[str, Any]:
        return self._request(f"/samples/{sample_id}/edit", body)


def resolve_token(explicit: str = "") -> str:
    """FLOW_API_TOKEN → --token → ~/.config/flow/api-token, matching the flowbio CLI."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Attach imported Flow samples to a project (post `samples import`)."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--sample-ids", required=True, help="Comma-separated sample ids from the import job"
    )
    parser.add_argument("--token", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    token = resolve_token(args.token)
    if not token:
        print(
            "No API token. Set FLOW_API_TOKEN, pass --token, or write "
            "~/.config/flow/api-token.",
            file=sys.stderr,
        )
        return 2

    sample_ids = [s.strip() for s in args.sample_ids.split(",") if s.strip()]
    result = assign_samples_to_project(
        RestFlowApi(token), sample_ids, args.project_id, dry_run=args.dry_run
    )
    verb = "would assign" if args.dry_run else "assigned"
    print(
        f"{verb}={result.planned if args.dry_run else result.assigned} "
        f"skipped={result.skipped} failed={result.failed}"
    )
    for sample_id, error in result.failures.items():
        print(f"  {sample_id}: {error}", file=sys.stderr)
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
