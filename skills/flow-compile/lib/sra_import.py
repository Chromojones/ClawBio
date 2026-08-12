"""Build the accession sheet for `flowbio samples import` (SRA/ENA → Flow, no download).

Three constraints are hard-won from the live API (GSE215250, flowbio 0.10.0) and are
enforced here rather than left to the caller:

1. **The accession must be an experiment (SRX/ERX/DRX), not a run.** A run accession is
   *accepted* and then **silently expanded to its parent experiment** — importing
   ``SRR3175580`` yielded one sample holding all four runs of ``SRX1590001`` (10 GB), and
   the job reported ``COMPLETED``. A study whose replicates are separate runs of one
   experiment therefore cannot be imported per replicate by this route at all.
   (An earlier revision of this file claimed ``HTTP 500``; re-tested 2026-08-12 on
   GSE78030, that is no longer the behaviour.)
2. **There is no ``project`` column.** flowbio's ``RESERVED_COLUMNS`` is
   ``(accession, name, organism, sample_type)``; anything else is treated as metadata and
   a stray ``project`` key is silently ignored, leaving samples unattached. Project
   assignment is a separate step — see ``lib/flow_project_assign.py``.
3. **``strandedness`` is rejected for CLIP** (``422 … not a valid attribute for this
   sample type``) even though ``samples batch-template --sample-type CLIP`` lists it as
   required. It is an RNA-Seq field.

Required for a CLIP import: ``accession``, ``sample_type``, ``name``,
``five_prime_barcode_sequence``, ``purification_target``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

#: Columns that must never reach the import sheet, with why.
FORBIDDEN_SHEET_COLUMNS: dict[str, str] = {
    "project": "the import API has no project field — assign after import",
    "strandedness": "RNA-Seq only; the CLIP import endpoint rejects it (422)",
    "reads1": "SRA-direct import has no local files",
    "reads2": "SRA-direct import has no local files",
}

_EXPERIMENT_RE = re.compile(r"^(SRX|ERX|DRX)\d+$", re.I)

#: annotation column -> import sheet column. Order defines the sheet's column order.
COLUMN_MAP: list[tuple[str, str]] = [
    ("Sample Name", "name"),
    ("Organism", "organism"),
    ("Experimental Method", "experimental_method"),
    ("Scientist", "scientist"),
    ("PI", "pi"),
    ("Organisation", "organisation"),
    ("Purification Agent", "purification_agent"),
    ("Protein (Purification Target)", "purification_target"),
    ("Purification Target Annotation", "purification_target__annotation"),
    ("Cell or Tissue", "source"),
    ("Source Annotation", "source__annotation"),
    ("Condition", "condition"),
    ("Sequencer", "sequencer"),
    ("5' Barcode Sequence", "five_prime_barcode_sequence"),
    ("3' Barcode Sequence", "three_prime_barcode_sequence"),
    ("GEO ID", "geo"),
    ("Comments", "comments"),
]

#: Flow rejects the whole import batch if any single `comments` value exceeds this.
#: Discovered on GSE76475: 11 rows refused because one was 1025 characters.
MAX_COMMENTS_CHARS = 1000

REQUIRED_CLIP_COLUMNS = (
    "accession",
    "sample_type",
    "name",
    "five_prime_barcode_sequence",
    "purification_target",
)


def is_experiment_accession(value: str) -> bool:
    """True for SRX/ERX/DRX experiment accessions (the only kind the import accepts)."""
    return bool(_EXPERIMENT_RE.match(str(value or "").strip()))


def _accession_for_row(row: pd.Series) -> str:
    for column in ("SRX", "srx", "Experiment", "ENA Experiment"):
        value = str(row.get(column, "") or "").strip()
        if value:
            return value
    return ""


def build_import_sheet(
    annotation: pd.DataFrame,
    *,
    sample_type: str = "CLIP",
) -> pd.DataFrame:
    """Map an annotation table onto a flowbio accession sheet.

    Empty optional metadata columns are dropped entirely rather than emitted blank, so an
    endogenous IP's empty tag annotation does not become a meaningless empty field.

    :raises ValueError: if any row lacks a usable SRX/ERX/DRX experiment accession.
    """
    if annotation is None or annotation.empty:
        return pd.DataFrame(columns=list(REQUIRED_CLIP_COLUMNS))

    records: list[dict[str, str]] = []
    for position, (_, row) in enumerate(annotation.iterrows(), start=1):
        accession = _accession_for_row(row)
        if not is_experiment_accession(accession):
            name = str(row.get("Sample Name", "")).strip() or f"row {position}"
            raise ValueError(
                f"{name}: {accession or '(missing)'!r} is not an experiment accession — "
                "flowbio samples import requires SRX/ERX/DRX. A run accession is ACCEPTED "
                "but silently expanded to its parent experiment: importing SRR3175580 "
                "produced one sample carrying all four runs of SRX1590001. The job reports "
                "COMPLETED, so the duplication surfaces nowhere. Populate the 'SRX' column "
                "of srr_map.tsv."
            )
        record: dict[str, str] = {"accession": accession, "sample_type": sample_type}
        for source_col, target_col in COLUMN_MAP:
            if target_col in FORBIDDEN_SHEET_COLUMNS:
                continue
            value = str(row.get(source_col, "") or "").strip()
            if value:
                record[target_col] = value
        records.append(record)

    sheet = pd.DataFrame(records)

    ordered = ["accession", "sample_type"] + [
        target for _, target in COLUMN_MAP if target in sheet.columns
    ]
    sheet = sheet[[c for c in ordered if c in sheet.columns]]

    for column in FORBIDDEN_SHEET_COLUMNS:
        if column in sheet.columns:
            sheet = sheet.drop(columns=[column])

    return validate_import_sheet(sheet)


def validate_import_sheet(sheet: pd.DataFrame) -> pd.DataFrame:
    """Refuse a sheet the import endpoint would reject, before the network call.

    One bad row fails the *whole* batch, and the API names the offender only by position
    (``7.metadata.comments``), so checking locally is much cheaper than decoding that.
    """
    missing = [c for c in REQUIRED_CLIP_COLUMNS if c not in sheet.columns]
    if missing:
        raise ValueError(
            f"import sheet missing required column(s): {', '.join(missing)} — "
            "CLIP imports require accession, sample_type, name, "
            "five_prime_barcode_sequence and purification_target"
        )

    if "comments" in sheet.columns:
        # Comments are where this skill records the evidence behind every judgement call, so
        # they grow naturally. Truncating would silently discard provenance — fail loudly and
        # name the rows so the author decides what to cut.
        over = [
            f"{row.get('name', f'row {position}')} ({len(str(row['comments']))} chars)"
            for position, (_, row) in enumerate(sheet.iterrows(), start=1)
            if len(str(row.get("comments") or "")) > MAX_COMMENTS_CHARS
        ]
        if over:
            raise ValueError(
                f"comments exceed Flow's {MAX_COMMENTS_CHARS}-character limit for: "
                f"{'; '.join(over)} — shorten them; one long row rejects the entire import"
            )
    return sheet


def write_import_sheet(output_dir: Path, sheet: pd.DataFrame) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "import_sheet.csv"
    sheet.to_csv(path, index=False)
    return path


def write_import_scripts(
    output_dir: Path,
    *,
    sheet_path: Path,
    project_id: str,
    poll_interval: int = 60,
) -> Path:
    """Emit sra_import.sh — import, poll to completion, then assign the project."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    script = output_dir / "sra_import.sh"
    assign_helper = Path(__file__).resolve().parent / "flow_project_assign.py"

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# Generated by flow-compile — direct SRA/ENA -> Flow import (no local download).",
        "# Auth: FLOW_API_TOKEN (or --token-file / ~/.config/flow/api-token).",
        "# Requires flowbio >= 0.10.0.",
        "",
        f'SHEET="{Path(sheet_path).resolve()}"',
        f'PROJECT_ID="{project_id}"',
        f'OUTPUT="{output_dir.resolve()}"',
        f'ASSIGN="{assign_helper}"',
        f"POLL={poll_interval}",
        "",
        'if [[ -z "${FLOW_API_TOKEN:-}" && ! -f "${HOME}/.config/flow/api-token" ]]; then',
        '  echo "Set FLOW_API_TOKEN (or write ~/.config/flow/api-token) first." >&2',
        "  exit 2",
        "fi",
        "",
        'echo "→ submitting import from $SHEET"',
        'JOB=$(flowbio --json samples import --sheet "$SHEET" \\',
        '  | python3 -c "import sys,json;print(json.load(sys.stdin)[\'id\'])")',
        'echo "  job id: $JOB"',
        "",
        "# The import is asynchronous; poll until it leaves RUNNING.",
        "while true; do",
        '  PAYLOAD=$(flowbio --json samples import-status --job-id "$JOB")',
        '  STATUS=$(echo "$PAYLOAD" | python3 -c "import sys,json;print(json.load(sys.stdin)[\'status\'])")',
        '  echo "  [$(date +%H:%M:%S)] $STATUS"',
        '  [[ "$STATUS" == "RUNNING" ]] || break',
        '  sleep "$POLL"',
        "done",
        "",
        'echo "$PAYLOAD" > "$OUTPUT/import_job.json"',
        'if [[ "$STATUS" != "COMPLETED" ]]; then',
        '  echo "Import did not complete (status=$STATUS) — see $OUTPUT/import_job.json" >&2',
        "  exit 1",
        "fi",
        "",
        "# Imported samples are NOT attached to a project (the sheet has no project field).",
        'echo "→ assigning samples to project $PROJECT_ID"',
        'SAMPLE_IDS=$(echo "$PAYLOAD" | python3 -c "import sys,json;print(\',\'.join(str(i) for i in json.load(sys.stdin)[\'sample_ids\']))")',
        'python3 "$ASSIGN" --project-id "$PROJECT_ID" --sample-ids "$SAMPLE_IDS"',
        "",
        'echo "✓ import complete — $OUTPUT/import_job.json"',
    ]
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return script
