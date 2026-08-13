#!/usr/bin/env python3
"""
Edit whitelisted fields on already-uploaded Flow.bio samples via REST /edit.

This is the post-upload "sample updating" tool used by flow-compile for the
ENA / ArrayExpress workflow (E-MTAB-432). It generalises the one-off
``fix_barcodes_and_submit.py`` that renamed samples and set 5' barcode patterns
after upload.

Unlike ``flow_public_samples_push_metadata_v2.py`` (which diffs two pull CSVs
and pushes purification/annotation fields via GraphQL + REST), this script:

  * takes a small edit CSV keyed by ``sample_id`` **or** by an accession token
    matched against the live sample name (e.g. ``ERR039788`` / ``SRR6181530``),
  * pushes any whitelisted scalar field (including ``five_prime_barcode_sequence``
    and ``name``, which the metadata-push script does not handle) via
    ``POST app.flow.bio/api/samples/{id}/edit``,
  * verifies each change with a follow-up GET.

Whitelisted edit columns:
  name, five_prime_barcode_sequence, three_prime_barcode_sequence,
  comments, condition, experimental_method, purification_agent,
  purification_target, source, sequencer

Credentials: FLOWBIO_USERNAME / FLOWBIO_PASSWORD or --username / --password.

Examples:
  # Match rows to samples by accession embedded in the sample name, dry-run:
  python3 flow_edit_samples.py --project-id 900095972507806297 \\
    --edits edits.csv --match-name --dry-run

  # Edit by explicit sample_id column and apply:
  python3 flow_edit_samples.py --edits edits.csv --yes

edits.csv (match-name mode) example:
  accession,name,five_prime_barcode_sequence,comments
  ERR039788,TIA1_Hs_HeLa_GAANNNN_LUd15_ERR039788,GAANNNN,iCLIP_..._GAANNNN_..._4.fq.gz

edits.csv (sample_id mode) example:
  sample_id,name,five_prime_barcode_sequence
  450873145213532192,TIA1_Hs_HeLa_GAANNNN_LUd15_ERR039788,GAANNNN
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

API_BASE = os.environ.get("FLOWBIO_API_BASE", "https://app.flow.bio/api").rstrip("/")

WHITELIST_EDIT_FIELDS: Tuple[str, ...] = (
    "name",
    "five_prime_barcode_sequence",
    "three_prime_barcode_sequence",
    "comments",
    "condition",
    "experimental_method",
    "purification_agent",
    "purification_target",
    # Annotation sub-fields (Flow renders them as `value:annotation`). Needed to set a
    # construct tag such as `cV5` or a cell-line lineage after upload.
    "purification_target__annotation",
    "source__annotation",
    # Attribution fields. Omitted originally, which left no way to repair the common
    # `pi = scientist.split()[-1]` fallback (PI recorded as the first author's surname)
    # without hand-written REST calls. Verified accepted by POST /samples/{id}/edit.
    "scientist",
    "pi",
    "organisation",
    "source",
    "sequencer",
    # A sample PROPERTY, not a metadata attribute — it lands beside `name`, which is why it
    # is absent from `samples batch-template` (that lists metadata columns only). Setting it
    # populates the owning project's `papers` with a resolved citation, so a PMID left in
    # `comments` loses the paper linkage entirely.
    "pubmed",
)

DEFAULT_ACCESSION_RE = r"(ERR\d+|SRR\d+|DRR\d+|GSM\d+)"


def live_value(live: dict, key: str) -> object:
    """Read an edited field back out of a GET /samples/{id} payload.

    Flow nests metadata — ``{"metadata": {"source": {"value": ..., "annotation": ...}}}`` —
    so a flat ``live.get("source__annotation")`` is always None and ``live.get("source")`` is
    a dict. Verifying against those produced a "verify mismatch" warning on every metadata
    edit that had in fact applied cleanly.

    Returns ``""`` for an annotation slot that is absent (no annotation *is* empty), and
    ``None`` for a field that does not exist at all.
    """
    metadata = live.get("metadata") or {}
    base, is_annotation, _ = key.partition("__annotation")
    if is_annotation:
        entry = metadata.get(base)
        return (entry.get("annotation") or "") if isinstance(entry, dict) else ""
    if key in live and not isinstance(live.get(key), dict):
        return live.get(key)
    entry = metadata.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry if entry is not None else live.get(key)


def _norm(value: object) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in ("nan", "none") else s


def login(session: requests.Session, username: str, password: str) -> str:
    r = session.post(
        f"{API_BASE}/login",
        json={"username": username, "password": password},
        timeout=60,
    )
    r.raise_for_status()
    token = r.json().get("token")
    if not token:
        raise RuntimeError("Login failed: no token returned")
    return str(token)


def fetch_project_samples(session: requests.Session, token: str, project_id: str) -> List[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    page = 1
    out: List[dict] = []
    while True:
        r = session.get(
            f"{API_BASE}/projects/{project_id}/samples",
            params={"page": page, "count": 100},
            headers=headers,
            timeout=60,
        )
        r.raise_for_status()
        batch = r.json().get("samples", [])
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out


def fetch_sample(session: requests.Session, token: str, sample_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    r = session.get(f"{API_BASE}/samples/{sample_id}", headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def edit_sample(
    session: requests.Session, token: str, sample_id: str, body: Dict[str, str]
) -> Tuple[bool, Optional[str]]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        r = session.post(
            f"{API_BASE}/samples/{sample_id}/edit", json=body, headers=headers, timeout=90
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if r.status_code >= 400:
        return False, f"HTTP {r.status_code}: {r.text[:600]}"
    return True, None


def load_edits(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            rows.append({k: _norm(v) for k, v in raw.items()})
    if not rows:
        raise SystemExit(f"No rows in {path}")
    return rows


#: Write this in an edits CSV cell to CLEAR a field. A blank cell cannot mean "clear" —
#: sparse sheets leave most cells blank and must not wipe those columns — so removing a
#: value has to be explicit. Needed because "empty" is a real value here: controls carry an
#: empty `purification_agent`, and a size-matched input carries no tag.
CLEAR_SENTINEL = "__CLEAR__"


def build_edit_body(row: Dict[str, str]) -> Dict[str, str]:
    body: Dict[str, str] = {}
    for column in WHITELIST_EDIT_FIELDS:
        if column not in row:
            continue
        value = row[column]
        if str(value).strip().upper() == CLEAR_SENTINEL:
            body[column] = ""
        elif value != "":
            body[column] = value
    return body


def resolve_by_name(
    edits: List[Dict[str, str]],
    samples: List[dict],
    accession_re: str,
) -> Tuple[List[Tuple[str, Dict[str, str]]], List[str]]:
    """Map each edit row to a sample_id by matching an accession token in the name."""
    pat = re.compile(accession_re)
    by_acc: Dict[str, str] = {}
    for s in samples:
        m = pat.search(str(s.get("name", "")))
        if m:
            by_acc[m.group(1)] = str(s["id"])
    resolved: List[Tuple[str, Dict[str, str]]] = []
    unmatched: List[str] = []
    for row in edits:
        acc = row.get("accession") or ""
        if not acc:
            m = pat.search(row.get("name", ""))
            acc = m.group(1) if m else ""
        sid = by_acc.get(acc)
        if not sid:
            unmatched.append(acc or json.dumps(row))
            continue
        resolved.append((sid, row))
    return resolved, unmatched


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--edits", type=Path, required=True, help="CSV of edits")
    ap.add_argument("--project-id", default="", help="Required with --match-name")
    ap.add_argument(
        "--match-name",
        action="store_true",
        help="Match edit rows to samples by accession in the sample name (needs --project-id)",
    )
    ap.add_argument(
        "--accession-regex",
        default=DEFAULT_ACCESSION_RE,
        help=f"Regex for the accession token in sample names (default: {DEFAULT_ACCESSION_RE})",
    )
    ap.add_argument("--username", default=os.environ.get("FLOWBIO_USERNAME", ""))
    ap.add_argument("--password", default=os.environ.get("FLOWBIO_PASSWORD", ""))
    ap.add_argument("--dry-run", action="store_true", help="Show planned edits only")
    ap.add_argument("--yes", action="store_true", help="Apply without prompting")
    ap.add_argument("--no-verify", action="store_true", help="Skip post-edit GET verification")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

    if not args.username or not args.password:
        logging.error("Set FLOWBIO_USERNAME/FLOWBIO_PASSWORD or use --username/--password")
        return 2

    edits = load_edits(args.edits)
    session = requests.Session()
    token = login(session, args.username, args.password)

    if args.match_name:
        if not args.project_id:
            logging.error("--match-name requires --project-id")
            return 2
        samples = fetch_project_samples(session, token, args.project_id)
        logging.info("Fetched %d samples from project %s", len(samples), args.project_id)
        resolved, unmatched = resolve_by_name(edits, samples, args.accession_regex)
        for u in unmatched:
            logging.warning("No sample matched accession: %s", u)
    else:
        resolved = []
        for row in edits:
            sid = row.get("sample_id")
            if not sid:
                logging.warning("Row missing sample_id (use --match-name?): %s", row)
                continue
            resolved.append((sid, row))

    planned: List[Tuple[str, Dict[str, str]]] = []
    for sid, row in resolved:
        body = build_edit_body(row)
        if not body:
            logging.warning("sample_id %s: no whitelisted fields to edit, skipped", sid)
            continue
        planned.append((sid, body))

    print(f"\n{len(planned)} sample(s) to edit:")
    for sid, body in planned:
        print(f"  {sid}: {json.dumps(body)}")

    if args.dry_run:
        print("\nDry run complete (no changes made).")
        return 0

    if not planned:
        logging.info("Nothing to do.")
        return 0

    if not args.yes:
        ans = input(f"\nApply {len(planned)} edit(s)? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 0

    ok_count = 0
    fail_count = 0
    for sid, body in planned:
        ok, err = edit_sample(session, token, sid, body)
        if not ok:
            fail_count += 1
            logging.error("Edit failed for %s: %s", sid, err)
            continue
        if not args.no_verify:
            live = fetch_sample(session, token, sid)
            mismatches = [
                k for k, v in body.items() if _norm(live_value(live, k)) != _norm(v)
            ]
            if mismatches:
                logging.warning("%s: verify mismatch on %s", sid, ",".join(mismatches))
        ok_count += 1
        print(f"updated {sid} -> {body.get('name', '(name unchanged)')}")

    logging.info("Done. updated=%d failed=%d", ok_count, fail_count)
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
