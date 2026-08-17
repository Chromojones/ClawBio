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
#: Controls whose defining feature is that **no antibody was used** — agent stays empty.
#:
#: `NOABCTRL` is beads with no antibody, which is NOT the same as `SMINPUT`: an input is
#: material carried through the protocol, a no-antibody control is an IP performed without
#: an antibody. GSE75418's yielded 595,480 reads against 14-40M for its IPs (~0.08% of the
#: SAFB1 read count). They answer different questions, so they stay distinct terms.
CONTROL_TARGETS = {"SMINPUT", "INPUT", "IGG", "NOABCTRL"}

#: An antibody pulldown performed on cells lacking the target (e.g. a myc IP on
#: untransfected cells). The antibody *was* used, so unlike SMInput the agent must be kept.
ANTIBODY_CONTROL_TARGETS = {"ABCONTROL"}

#: Agent values that are correct as literals (no vendor/catalog applies).
ALLOWED_AGENT_LITERALS = {
    "no antibody": "no antibody",
    "strep/his affinity tag purification": "Strep/His affinity tag purification",
}

#: The parenthetical is OPTIONAL. When no catalog reagent exists (an antibody shared between
#: labs, common in tissue CLIP and pre-2015 studies) the agent is the bare canonical form and
#: the provenance goes in **Comments**. Requiring `anti-` still rejects the vendor-less prose
#: forms — `NOVA antibody`, `anti-NOVA antibody`, `V5-antibody` — because the trailing word
#: leaves the pattern unanchored; those signal an unfinished lookup, not a gift antibody.
_AGENT_RE = re.compile(
    rf"^(?:(?P<species>{'|'.join(SPECIES)})\s+)?"
    r"anti[-\s]?(?P<target>[A-Za-z0-9][A-Za-z0-9./-]*)"
    r"(?:\s*\((?P<inner>[^()]+)\))?$",
    re.I,
)
#: An antibody shared by another lab has no vendor and no catalog number — there is nothing
#: to buy. E-MTAB-1008 immunoprecipitated Nova with an antibody acknowledged as shared by
#: Robert B Darnell; tissue CLIP and pre-2015 studies hit this routinely. The provenance must
#: NAME a source, so a bare `(gift)` cannot be used to dodge the vendor requirement.
_GIFT_INNER_RE = re.compile(r"^gift\s*(?::|from\b)\s*(?P<source>.+)$", re.I)

_CATALOG_PREFIX_RE = re.compile(r"^(?:cat(?:alogue|alog)?\.?\s*#?|#)\s*", re.I)
#: Antibody dilutions (`1:500`, `1:1,000`) live in the same sentence as the antibody and
#: parse as a "catalog" unless explicitly rejected.
_DILUTION_RE = re.compile(r"^\d+\s*:\s*[\d,]+$")
_DILUTION_ANYWHERE_RE = re.compile(r"\b\d+\s*:\s*\d[\d,]*\b")


def gift_provenance(value: str) -> str:
    """The named source of a gift antibody, or ``""``.

    ``Anti-Nova (gift: Darnell lab)`` → ``Darnell lab``. A parenthetical that names nobody
    (``(gift)``, ``(gift: )``) yields ``""`` and is therefore not a valid agent.
    """
    match = _AGENT_RE.match(re.sub(r"\s+", " ", str(value or "")).strip())
    if not match:
        return ""
    gift = _GIFT_INNER_RE.match((match.group("inner") or "").strip())
    if not gift:
        return ""
    source = gift.group("source").strip().strip(",").strip()
    return source if any(ch.isalpha() for ch in source) else ""


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
    species = (match.group("species") or "").strip().title()
    target = match.group("target").strip().upper()
    prefix = f"{species} " if species else ""
    inner = (match.group("inner") or "").strip()

    # No parenthetical, or a gift provenance that belongs in Comments rather than the agent:
    # both resolve to the bare canonical form so there is exactly one convention on Flow.
    if not inner or inner.lower() == "gift" or _GIFT_INNER_RE.match(inner):
        return f"{prefix}Anti-{target}"

    vendor, catalog = split_vendor_catalog(inner)
    if not vendor or not looks_like_catalog(catalog):
        return ""
    if species:
        return format_agent(species, target, vendor, catalog)
    return f"Anti-{target} ({vendor} {catalog})"


def agent_target(value: str) -> str:
    """The protein an antibody string names, or ``""``."""
    collapsed = re.sub(r"\s+", " ", str(value or "")).strip()
    match = _AGENT_RE.match(collapsed)
    return match.group("target").upper() if match else ""


def validate_purification_agent(
    value: str, *, target: str = "", annotation: str = ""
) -> list[Check]:
    value = str(value or "").strip()
    target_upper = str(target or "").strip().upper()
    field = "Purification Agent"

    if target_upper in ANTIBODY_CONTROL_TARGETS:
        # The antibody was applied to cells lacking the target — it is still the agent.
        if not value:
            return [
                Check(
                    ERROR,
                    f"{target} is an antibody control and must record the antibody used",
                    field,
                )
            ]
        return _validate_agent_string(value, target=target, field=field, annotation=annotation)

    if target_upper in CONTROL_TARGETS:
        # Convention: controls carry an EMPTY agent, so "has an agent" is a clean proxy for
        # "is an IP". The literal "no antibody" is tolerated as legacy data but warned.
        if not value:
            return []
        if value.lower() == "no antibody":
            return [
                Check(
                    WARNING,
                    f"control target {target} uses the legacy literal 'no antibody'; "
                    "the convention is an empty purification agent",
                    field,
                )
            ]
        return [
            Check(
                ERROR,
                f"control target {target} must have an empty purification agent, got {value!r}",
                field,
            )
        ]

    if not value:
        return [Check(ERROR, "purification agent is empty", field)]

    return _validate_agent_string(value, target=target, field=field, annotation=annotation)


def _validate_agent_string(
    value: str, *, target: str, field: str, annotation: str = ""
) -> list[Check]:
    """Shape + target-agreement checks for a non-empty antibody string."""
    target_upper = str(target or "").strip().upper()
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
    if "(" not in normalized and normalized not in ALLOWED_AGENT_LITERALS.values():
        # Legitimate (a shared or in-house antibody), but unverifiable and unpurchasable, so
        # the researcher confirms no catalog reagent was simply missed. Provenance is not
        # discarded — it belongs in Comments, where it does not pollute the agent vocabulary.
        gift = gift_provenance(value)
        origin = f" (provenance found: {gift!r})" if gift else ""
        checks.append(
            Check(
                WARNING,
                f"{normalized!r} names no vendor or catalog{origin}; confirm the study used a "
                "shared/in-house antibody and record its provenance in the sample comments",
                field,
            )
        )
    if normalized in ALLOWED_AGENT_LITERALS.values():
        checks.append(
            Check(WARNING, f"target {target} has agent {normalized!r}; confirm this is a control", field)
        )
        return checks
    named = agent_target(value)
    # An antibody control is *defined* by the antibody naming something other than the row's
    # target (a myc IP on untransfected cells), so the agreement check does not apply.
    if target_upper in ANTIBODY_CONTROL_TARGETS:
        return checks
    # A tagged pulldown's antibody names the TAG, not the protein: `Anti-Myc` against target
    # LARP6 with annotation `nMYC` is correct by construction, not a mismatch.
    tag = re.sub(r"^[cn]", "", str(annotation or "").strip(), count=1).upper()
    if tag and named and named == tag:
        return checks
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
    # T7 gene 10 leader peptide (MASMTGGQQMG) — as standard as FLAG, and half of
    # E-MTAB-2700's design (APOBEC3G/3F expressed as both T7- and GFP-tagged constructs).
    "T7",
)
#: Annotation grammar: an optional protein alteration, then the tag — mutation first, tag
#: last, hyphen-separated. Flow renders it as `TARGET:annotation`, so a myc-tagged LARP6
#: missing its N-terminal region reads `LARP6:dNTR-nMYC`.
#: The tag alternation is longest-first and anchored at the end, so `c3xFLAG-HBH` parses as
#: one composite tag rather than mutation `c3xFLAG` plus tag `HBH`.
_TAG_ALT = "|".join(re.escape(t) for t in TAGS)
_TAG_RE = re.compile(rf"^(?:(?P<mutation>[A-Za-z0-9_.]+)-)?(?P<tag>[cn](?:{_TAG_ALT}))$")
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


#: Flow's organism vocabulary, from `GET /api/organisms`. The API takes the CODE; the
#: `name` and `latin_name` it returns are for display and are rejected on submission.
ORGANISM_CODES: dict[str, str] = {
    "Hs": "Homo sapiens",
    "Mm": "Mus musculus",
    "Rn": "Rattus norvegicus",
    "Dr": "Danio rerio",
    "Dm": "Drosophila melanogaster",
    "Sc": "Saccharomyces cerevisiae",
    "Ec": "Escherichia coli",
    "Gg": "Gallus gallus",
    "At": "Arabidopsis thaliana",
    "Vf": "Vibrio fischeri",
}

#: Latin and common names mapped back to the code, so the error can say what to use instead.
_ORGANISM_ALIASES: dict[str, str] = {
    **{latin.lower(): code for code, latin in ORGANISM_CODES.items()},
    "human": "Hs", "mouse": "Mm", "rat": "Rn", "zebrafish": "Dr",
    "drosophila": "Dm", "yeast": "Sc", "e. coli": "Ec", "chicken": "Gg",
    "arabidopsis": "At", "v. fischeri": "Vf",
}


def validate_organism(value: str) -> list[Check]:
    """Organism must be Flow's two-letter code, not a Latin or common name.

    GSE159997's upload sheet carried ``Mus musculus`` and every row was rejected with
    ``{'organism': ['Does not exist.']}`` — after the FASTQs had been staged and the
    uploader had started walking rows. Both the import and the upload path take the code;
    there is no asymmetry between them, the Latin name is simply wrong everywhere.

    Case-sensitive, because the API is: accepting ``mm`` here would only move the failure
    downstream.
    """
    field = "Organism"
    raw = str(value or "").strip()
    if not raw:
        return [Check(ERROR, "organism is empty", field)]
    if raw in ORGANISM_CODES:
        return []
    suggestion = _ORGANISM_ALIASES.get(raw.lower()) or _ORGANISM_ALIASES.get(raw.strip().lower())
    if suggestion is None and raw.lower() in {c.lower() for c in ORGANISM_CODES}:
        suggestion = next(c for c in ORGANISM_CODES if c.lower() == raw.lower())
    if suggestion:
        return [Check(
            ERROR,
            f"organism {raw!r} is not a Flow code — use {suggestion!r} "
            f"({ORGANISM_CODES[suggestion]}). The API accepts the code only; the Latin and "
            f"common names it returns are for display.",
            field,
        )]
    return [Check(
        ERROR,
        f"organism {raw!r} is not one of Flow's codes ({', '.join(sorted(ORGANISM_CODES))})",
        field,
    )]


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


#: A replicate label in a sample name: `Rep1`, `rep_2`, `REP 3`.
_REPLICATE_RE = re.compile(r"(?<![A-Za-z])rep[\s_-]?(\d+)", re.I)


def replicate_token(sample_name: str) -> str:
    """The replicate number in a sample name, or ``""`` if it carries none."""
    match = _REPLICATE_RE.search(str(sample_name or ""))
    return match.group(1) if match else ""


def find_replicate_collisions(annotation: pd.DataFrame) -> list[MetadataIssue]:
    """Two rows sharing target + condition + replicate number lost a distinction.

    Nothing can be replicate 1 of the same target under the same condition twice. When it
    happens, some variable that separates the two samples was dropped — overwhelmingly, an
    eCLIP size-matched input recorded as though it were the IP.

    This exists because the control check in `validate_target_and_annotation` keys off the
    sample **name** containing `input`/`SMInput`. On GSE290281's first batch the naming step
    had failed in exactly the same way, so that check saw nothing and 8 mislabelled inputs
    passed clean. A guardrail must not depend solely on the field that is also wrong.

    Condition participates in the key so legitimate designs survive: GSE76475 has RBFOX1
    replicate 1 in both the HMW and soluble fractions, which is not a collision.
    """
    groups: dict[tuple[str, str, str], list[str]] = {}
    for _, row in annotation.iterrows():
        name = str(row.get("Sample Name", "")).strip()
        replicate = replicate_token(name)
        if not replicate:
            continue
        target = str(row.get("Protein (Purification Target)", "")).strip().upper()
        # Control targets are shared placeholders, not proteins: every IP's size-matched
        # input carries SMInput, so `SMInput + rep1` collides across unrelated proteins by
        # design. Exempting them keeps the check silent on correct studies — and detection
        # is unaffected, since the bug this was built for had two rows carrying a real
        # protein target.
        if target in CONTROL_TARGETS or target in ANTIBODY_CONTROL_TARGETS:
            continue
        # The tag annotation is part of the sample's identity — Flow renders the pair as
        # `TARGET:annotation`. E-MTAB-2700 expresses each target as both a T7- and a
        # GFP-tagged construct, so APOBEC3G + producer cell + replicate 1 legitimately
        # exists twice, distinguished only by `nT7` vs `nGFP`. Excluding it from the key
        # would flag 12 correct rows and push the tag into Condition to appease the check.
        key = (
            target,
            str(row.get("Purification Target Annotation", "") or "").strip().upper(),
            str(row.get("Condition", "") or "").strip().lower(),
            replicate,
        )
        groups.setdefault(key, []).append(name)

    issues: list[MetadataIssue] = []
    for (target, tag, condition, replicate), names in groups.items():
        if len(names) < 2:
            continue
        where = f" under condition {condition!r}" if condition else ""
        where += f" with tag {tag!r}" if tag else ""
        issues.append(
            MetadataIssue(
                row=0,
                sample_name=", ".join(sorted(names)),
                field="Sample Name",
                severity=ERROR,
                message=(
                    f"{len(names)} samples share target {target} and replicate {replicate}"
                    f"{where}: {', '.join(sorted(names))} — a distinction was lost. If one is "
                    "a size-matched input it must carry target 'SMInput' with an empty "
                    "purification agent; otherwise set Condition to separate them"
                ),
            )
        )
    return issues


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
        # NB: named `tag_annotation`, not `annotation` — the latter is this function's
        # DataFrame parameter, and shadowing it broke the cross-row check below.
        tag_annotation = str(row.get("Purification Target Annotation", "")).strip()
        row_no = int(idx) + 2

        checks: list[Check] = []
        checks += validate_purification_agent(agent, target=target, annotation=tag_annotation)
        checks += validate_source(str(row.get("Cell or Tissue", "")))
        checks += validate_target_and_annotation(
            target=target,
            annotation=tag_annotation,
            agent=agent,
            sample_name=sample,
        )
        checks += validate_five_prime_barcode(
            str(row.get("5' Barcode Sequence", "")), umi_header_format=umi_header_format
        )
        # Only when the sheet carries the column — edit sheets legitimately omit it.
        if "Organism" in annotation.columns:
            checks += validate_organism(str(row.get("Organism", "")))

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

    # Cross-row check: needs the whole table, so it cannot live in the per-row loop.
    issues.extend(find_replicate_collisions(annotation))
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
