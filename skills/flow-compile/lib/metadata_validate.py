"""Metadata accuracy guardrails for the Flow annotation table.

The three fields below are the ones that drift between models, because the GEO series
matrix either omits them or states them loosely, leaving the agent to choose:

  * ``Purification Agent``  — the antibody. GEO usually has nothing; the paper's Key
    Resources table often lists several antibodies for the same protein (Western vs
    IP), so only the assay-specific Methods sentence identifies the right one.
  * ``Cell or Tissue``      — GEO ``source_name_ch1`` is frequently a supplier phrase
    ("ATCC Cell Lines") or a generic descriptor ("human embryonic kidney") rather than
    the actual line (HeLa, HEK293T).
  * ``Purification Target Annotation`` — the tag (GFP/FLAG/V5...). Must be empty for an
    endogenous IP and must never be invented for a size-matched input.

This module is **pure and offline**: it validates what has already been assembled and
hands the researcher a confirmation hook. It never rewrites a value silently — the one
transformation it does perform, :func:`normalize_purification_agent`, only collapses
formatting variants of the *same* antibody onto one canonical spelling.

Severity contract: ``ERROR`` blocks the pipeline until the researcher approves;
``WARNING`` is surfaced for review but does not block.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from lib.vendor.flow_api.metadata.parse_key_resources_antibodies import format_agent

ERROR = "error"
WARNING = "warning"


class Check(NamedTuple):
    """One validator finding. Indexable as (severity, message) by design."""

    severity: str
    message: str
    field: str = ""


@dataclass
class MetadataIssue:
    row: int
    sample_name: str
    field: str
    severity: str
    message: str


# --------------------------------------------------------------------------- agents

#: Host species that may prefix an antibody name. Extend as new studies appear.
SPECIES = (
    "goat", "rabbit", "mouse", "rat", "sheep", "donkey", "chicken", "human", "llama",
)
SPECIES_UPPER = {s.upper() for s in SPECIES}

#: Targets that denote a control library rather than an immunoprecipitated protein.
CONTROL_TARGETS = {"SMINPUT", "INPUT", "IGG"}

#: Agent values that are correct as literals (no vendor/catalog applies).
ALLOWED_AGENT_LITERALS = {
    "no antibody": "no antibody",
    "strep/his affinity tag purification": "Strep/His affinity tag purification",
}

_AGENT_RE = re.compile(
    rf"^(?:(?P<species>{'|'.join(SPECIES)})\s+)?"
    r"anti[-\s]?(?P<target>[A-Za-z0-9][A-Za-z0-9./-]*)"
    r"\s*\((?P<inner>[^()]+)\)$",
    re.I,
)
_CATALOG_PREFIX_RE = re.compile(r"^(?:cat(?:alogue|alog)?\.?\s*#?|#)\s*", re.I)
#: Antibody dilutions (`1:500`, `1:1,000`) live in the same sentence as the antibody and
#: parse as a "catalog" unless explicitly rejected.
_DILUTION_RE = re.compile(r"^\d+\s*:\s*[\d,]+$")
_DILUTION_ANYWHERE_RE = re.compile(r"\b\d+\s*:\s*\d[\d,]*\b")


def looks_like_catalog(value: str) -> bool:
    """A catalog number contains a digit and is not a dilution ratio."""
    value = (value or "").strip()
    if not value or _DILUTION_RE.match(value):
        return False
    return any(ch.isdigit() for ch in value)


def split_vendor_catalog(inner: str) -> tuple[str, str]:
    """Split the parenthesised part into (vendor, catalog).

    Handles ``Thermo Fisher PA5-31650``, ``Thermo Fisher, PA5-31650`` and
    ``Thermo Fisher, cat# PA5-31650``.
    """
    # Strip any dilution ratio first — `1:1,000` otherwise splits into a bogus "000" catalog.
    inner = _DILUTION_ANYWHERE_RE.sub(" ", inner or "").strip().strip(",").strip()
    vendor, sep, catalog = inner.rpartition(",")
    if not sep:
        vendor, _, catalog = inner.rpartition(" ")
    vendor = vendor.strip()
    catalog = _CATALOG_PREFIX_RE.sub("", catalog.strip()).strip()
    return vendor, catalog


def normalize_purification_agent(value: str) -> str:
    """Collapse formatting variants onto the canonical Flow spelling.

    ``Rabbit anti-PARP13 (Thermo Fisher, cat# PA5-31650)``
    → ``Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)``

    Returns ``""`` when the value is not a parseable antibody — that includes the
    vendor-less forms this skill itself used to synthesize (``CPSF5 antibody``,
    ``V5-antibody``), which are exactly the values we must stop accepting.
    """
    collapsed = re.sub(r"\s+", " ", str(value or "")).strip()
    if not collapsed:
        return ""
    literal = ALLOWED_AGENT_LITERALS.get(collapsed.lower())
    if literal:
        return literal
    match = _AGENT_RE.match(collapsed)
    if not match:
        return ""
    vendor, catalog = split_vendor_catalog(match.group("inner"))
    if not vendor or not looks_like_catalog(catalog):
        return ""
    species = (match.group("species") or "").strip().title()
    target = match.group("target").strip().upper()
    if species:
        return format_agent(species, target, vendor, catalog)
    return f"Anti-{target} ({vendor} {catalog})"


def agent_target(value: str) -> str:
    """The protein an antibody string names, or ``""``."""
    collapsed = re.sub(r"\s+", " ", str(value or "")).strip()
    match = _AGENT_RE.match(collapsed)
    return match.group("target").upper() if match else ""


def validate_purification_agent(value: str, *, target: str = "") -> list[Check]:
    value = str(value or "").strip()
    target_upper = str(target or "").strip().upper()
    field = "Purification Agent"

    if target_upper in CONTROL_TARGETS:
        if value.lower() != "no antibody":
            return [
                Check(
                    ERROR,
                    f"control target {target} must use 'no antibody', got {value!r}",
                    field,
                )
            ]
        return []

    if not value:
        return [Check(ERROR, "purification agent is empty", field)]

    normalized = normalize_purification_agent(value)
    if not normalized:
        return [
            Check(
                ERROR,
                f"{value!r} is not a resolvable antibody — expected "
                "'<Species> Anti-<TARGET> (<Vendor> <Catalog>)' from the assay-specific "
                "Methods sentence",
                field,
            )
        ]

    checks: list[Check] = []
    if normalized in ALLOWED_AGENT_LITERALS.values():
        checks.append(
            Check(WARNING, f"target {target} has agent {normalized!r}; confirm this is a control", field)
        )
        return checks
    named = agent_target(value)
    if named and target_upper and named != target_upper:
        checks.append(
            Check(
                WARNING,
                f"antibody names {named} but purification target is {target_upper} — "
                "check you took the antibody from the right assay",
                field,
            )
        )
    return checks


# --------------------------------------------------------------------------- source

#: Supplier / placeholder phrases that are never a cell line or tissue.
_SUPPLIER_SOURCE_RE = re.compile(
    r"^(atcc\b.*|.*\bcell lines?$|cell type|tissue|n/?a|none|unknown|not applicable)$",
    re.I,
)

#: Descriptive names that shadow a specific line (GEO writes these in source_name_ch1).
GENERIC_SOURCE_DESCRIPTORS = {
    "human embryonic kidney",
    "embryonic kidney",
    "human embryonic kidney cells",
    "cervical carcinoma",
    "cervical cancer",
    "immortalized cells",
    "cell line",
}

#: Lines routinely confused with a near-identical relative. Never auto-corrected.
AMBIGUOUS_SOURCES = {
    "HEK293": "HEK293T",
    "HEK 293": "HEK293T",
    "293": "HEK293T",
    "293T": "HEK293T",
    "U2OS/U2-OS": "U2OS",
}


def validate_source(value: str) -> list[Check]:
    value = str(value or "").strip()
    field = "Cell or Tissue"
    if not value:
        return [Check(ERROR, "source (cell or tissue) is empty", field)]
    if _SUPPLIER_SOURCE_RE.match(value):
        return [
            Check(
                ERROR,
                f"{value!r} is a supplier/placeholder phrase, not a cell line — take the "
                "line from the paper's Key Resources or the GEO 'cell line:' characteristic",
                field,
            )
        ]
    if value.lower() in GENERIC_SOURCE_DESCRIPTORS:
        return [
            Check(
                ERROR,
                f"{value!r} is a generic descriptor, not a specific line — "
                "resolve it against the paper (e.g. 'human embryonic kidney' → HEK293T)",
                field,
            )
        ]
    alternative = AMBIGUOUS_SOURCES.get(value.upper()) or AMBIGUOUS_SOURCES.get(value)
    if alternative and alternative.upper() != value.upper():
        return [
            Check(
                WARNING,
                f"{value!r} is easily confused with {alternative!r} — confirm against the "
                "paper's Key Resources before upload",
                field,
            )
        ]
    return []


# ------------------------------------------------------------- target and annotation

#: Recognised affinity tags. Prefix is terminal: ``c`` (C-terminal) or ``n`` (N-terminal).
TAGS = (
    "3xFLAG-HBH", "3xFLAG", "FLAG", "GFP", "V5", "HA", "MYC", "HBH", "HIS", "TAP",
    "SNAP", "HALO", "MS2",
)
_TAG_RE = re.compile(rf"^[cn](?:{'|'.join(re.escape(t) for t in TAGS)})$")
_GENE_RE = re.compile(r"^[A-Z][A-Z0-9-]{1,15}$")


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^A-Za-z0-9]+", str(name or "").upper()) if t}


def validate_target_and_annotation(
    *,
    target: str,
    annotation: str,
    agent: str = "",
    sample_name: str = "",
) -> list[Check]:
    checks: list[Check] = []
    target_raw = str(target or "").strip()
    target_upper = target_raw.upper()
    annotation = str(annotation or "").strip()
    tfield = "Protein (Purification Target)"
    afield = "Purification Target Annotation"

    tokens = _name_tokens(sample_name)
    looks_like_control = bool(tokens & {"SMINPUT", "INPUT"})

    if not target_raw:
        checks.append(Check(ERROR, "purification target is empty", tfield))
    elif looks_like_control and target_upper not in CONTROL_TARGETS:
        checks.append(
            Check(
                ERROR,
                f"sample name marks this as an input but target is {target_raw!r} — a "
                "size-matched input must use target 'SMInput', never the IP's protein",
                tfield,
            )
        )
    elif target_upper not in CONTROL_TARGETS and target_upper != "GFP":
        if target_upper.startswith("ANTI") or target_upper in SPECIES_UPPER:
            checks.append(
                Check(
                    ERROR,
                    f"{target_raw!r} is an antibody fragment, not a gene symbol",
                    tfield,
                )
            )
        elif not _GENE_RE.match(target_upper):
            checks.append(
                Check(ERROR, f"{target_raw!r} is not a valid gene symbol", tfield)
            )

    if annotation and not _TAG_RE.match(annotation):
        checks.append(
            Check(
                ERROR,
                f"{annotation!r} is not valid tag grammar — expected a terminal prefix "
                f"'c' or 'n' plus a known tag, e.g. c3xFLAG-HBH, cV5, nFLAG "
                f"(known tags: {', '.join(TAGS)})",
                afield,
            )
        )
    if annotation and target_upper in CONTROL_TARGETS:
        checks.append(
            Check(ERROR, f"control target {target_raw} must not carry a tag annotation", afield)
        )
    return checks


# -------------------------------------------------------------------------- barcodes

_BARCODE_RE = re.compile(r"^[ACGTN]+$")


def validate_five_prime_barcode(value: str, *, umi_header_format: str = "") -> list[Check]:
    value = str(value or "").strip()
    field = "5' Barcode Sequence"
    if not value:
        return [Check(ERROR, "5' barcode is empty", field)]
    if not _BARCODE_RE.match(value):
        return [
            Check(
                ERROR,
                f"{value!r} contains characters outside A/C/G/T/N — Flow metadata accepts "
                "only ACGTN (normalize IUPAC codes to N before upload)",
                field,
            )
        ]
    umi_header_format = str(umi_header_format or "").strip()
    if umi_header_format and len(umi_header_format) != len(value):
        return [
            Check(
                WARNING,
                f"barcode length {len(value)} does not match umi_header_format length "
                f"{len(umi_header_format)} — the execution format must be all-N of the "
                "same length as the 5' barcode",
                field,
            )
        ]
    return []


# ----------------------------------------------------------------------- table level


def validate_annotation_table(
    annotation: pd.DataFrame,
    *,
    umi_header_format: str = "",
) -> list[MetadataIssue]:
    """Validate every row; row numbers are 1-based including the header line."""
    issues: list[MetadataIssue] = []
    if annotation is None or annotation.empty:
        return issues

    for idx, row in annotation.iterrows():
        sample = str(row.get("Sample Name", "")).strip()
        target = str(row.get("Protein (Purification Target)", "")).strip()
        agent = str(row.get("Purification Agent", "")).strip()
        row_no = int(idx) + 2

        checks: list[Check] = []
        checks += validate_purification_agent(agent, target=target)
        checks += validate_source(str(row.get("Cell or Tissue", "")))
        checks += validate_target_and_annotation(
            target=target,
            annotation=str(row.get("Purification Target Annotation", "")),
            agent=agent,
            sample_name=sample,
        )
        checks += validate_five_prime_barcode(
            str(row.get("5' Barcode Sequence", "")), umi_header_format=umi_header_format
        )

        for check in checks:
            issues.append(
                MetadataIssue(
                    row=row_no,
                    sample_name=sample,
                    field=check.field,
                    severity=check.severity,
                    message=check.message,
                )
            )
    return issues


def has_blocking_issues(issues: list[MetadataIssue]) -> bool:
    return any(i.severity == ERROR for i in issues)


def write_metadata_hook(output_dir: Path, issues: list[MetadataIssue]) -> Path:
    """Write CONFIRM_METADATA.md + metadata_validation.json (the researcher's gate)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "CONFIRM_METADATA.md"

    errors = [i for i in issues if i.severity == ERROR]
    warnings = [i for i in issues if i.severity == WARNING]

    lines = [
        "# Metadata accuracy hook — researcher confirmation required",
        "",
        "Scraped metadata was checked against `reference/metadata-accuracy-checklist.md`.",
        "Fix the errors below (or confirm they are correct) before uploading.",
        "",
        f"- **Errors (blocking):** {len(errors)}",
        f"- **Warnings (review):** {len(warnings)}",
        "",
    ]
    if not issues:
        lines += ["No metadata issues — all tracked fields specific and well-formed.", ""]
    else:
        lines += [
            "| Row | Sample | Field | Severity | Issue |",
            "|-----|--------|-------|----------|-------|",
        ]
        for i in errors + warnings:
            lines.append(
                f"| {i.row} | `{i.sample_name}` | {i.field} | {i.severity} | {i.message} |"
            )
        lines += [
            "",
            "## Release the gate",
            "",
            "After correcting the annotation (or confirming the values are right), re-run with:",
            "",
            "```bash",
            "--accept-metadata",
            "```",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")

    (output_dir / "metadata_validation.json").write_text(
        json.dumps(
            {
                "error_count": len(errors),
                "warning_count": len(warnings),
                "issues": [asdict(i) for i in issues],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
