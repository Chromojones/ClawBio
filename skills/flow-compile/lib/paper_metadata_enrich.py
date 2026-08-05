"""Enrich Flow annotation rows from linked publication (PI, purification agents)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from lib.metadata_validate import (
    ALLOWED_AGENT_LITERALS,
    SPECIES,
    split_vendor_catalog,
)
from lib.vendor.flow_api.metadata.parse_key_resources_antibodies import format_agent

#: Vendor-less antibody shapes. These are exactly the strings flow-compile itself used to
#: synthesize (`CPSF5 antibody` from flow_annotate.purification_agent, `V5-antibody`), so
#: they must be flagged rather than silently accepted as a real purification agent.
GENERIC_AGENT_RE = re.compile(
    r"^(?:(?:anti-)?[\w-]+[-\s]antibody|rbp[- ]specific antibody)$",
    re.I,
)
ANTIBODY_METHODS_RE = re.compile(
    rf"(?:(?P<species>{'|'.join(SPECIES)})[-\s]+)?"
    r"anti[-\s]?(?P<target>[A-Za-z][A-Za-z0-9-]{1,15})\b"
    r"[^.]{0,160}?\((?P<inner>[^()]+)\)",
    re.I,
)
#: A sentence mentioning one of these describes the CLIP assay itself. When a paper lists
#: several antibodies for the same protein (Western vs IP), the assay sentence wins.
ASSAY_SENTENCE_RE = re.compile(
    r"\b(e?CLIP|iCLIP2?|seCLIP|PAR-?CLIP|HITS-?CLIP|CLAP|crosslink\w*|"
    r"immunoprecipitat\w*)\b",
    re.I,
)
TARGET_ALIASES = {"TIAR": "TIAL1"}
SKIP_TARGETS = {"SMINPUT", "INPUT", "IGG", "GFP"}


@dataclass
class AnnotationWarning:
    row: int
    sample_name: str
    field: str
    message: str


@dataclass
class PaperMetadata:
    pmid: str
    title: str
    authors: list[str]
    first_author: str
    last_author: str
    pmcid: str
    methods_text: str


def _http_get(url: str, *, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "flow-compile/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc


def fetch_pubmed_record(pmid: str) -> tuple[str, list[str]]:
    """Return (title, authors as 'Fore Last')."""
    pmid = str(pmid).strip()
    if not pmid:
        return "", []
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={pmid}&retmode=xml"
    )
    try:
        root = ET.fromstring(_http_get(url))
    except (RuntimeError, ET.ParseError, urllib.error.URLError):
        return "", []
    title = (root.findtext(".//ArticleTitle") or "").strip()
    authors: list[str] = []
    for au in root.findall(".//Author"):
        last = (au.findtext("LastName") or "").strip()
        fore = (au.findtext("ForeName") or "").strip()
        if last:
            authors.append(f"{fore} {last}".strip())
    return title, authors


def _pmcid_for_pmid(pmid: str) -> str:
    url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query=EXT_ID:{pmid}&format=json&resultType=core&pageSize=1"
    )
    try:
        payload = json.loads(_http_get(url).decode())
    except (RuntimeError, json.JSONDecodeError, urllib.error.URLError):
        return ""
    results = payload.get("resultList", {}).get("result", [])
    if not results:
        return ""
    return str(results[0].get("pmcid") or "").strip()


def fetch_pmc_methods_text(pmcid: str) -> str:
    if not pmcid:
        return ""
    pmcid = pmcid.upper()
    if not pmcid.startswith("PMC"):
        pmcid = f"PMC{pmcid}"
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    try:
        root = ET.fromstring(_http_get(url))
    except (urllib.error.HTTPError, ET.ParseError):
        return ""
    parts: list[str] = []
    for sec in root.findall(".//sec"):
        title = (sec.findtext("title") or "").strip().lower()
        if title in {"methods", "materials and methods", "experimental procedures"}:
            parts.append(" ".join(sec.itertext()))
    if not parts:
        parts.append(" ".join(root.itertext()))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def load_paper_metadata(pmid: str, *, paper_text: str = "") -> PaperMetadata:
    title, authors = fetch_pubmed_record(pmid)
    excerpt = paper_text.strip()
    # An attached excerpt AUGMENTS the full Methods, it does not replace them. Replacing
    # made antibody resolution depend on which paragraph the agent happened to paste —
    # the excerpt is usually the barcode section, which contains no antibody at all.
    pmcid = _pmcid_for_pmid(pmid)
    fetched = fetch_pmc_methods_text(pmcid) if pmcid else ""
    methods = "\n\n".join(part for part in (excerpt, fetched) if part)
    first_author = authors[0] if authors else ""
    last_author = authors[-1] if authors else ""
    return PaperMetadata(
        pmid=str(pmid).strip(),
        title=title,
        authors=authors,
        first_author=first_author,
        last_author=last_author,
        pmcid=pmcid,
        methods_text=methods,
    )


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+", text or "") if s.strip()]


def _agent_string(species: str, target: str, vendor: str, catalog: str) -> str:
    if species:
        return format_agent(species.title(), target, vendor, catalog)
    return f"Anti-{target} ({vendor} {catalog})"


def extract_antibodies_from_text(text: str) -> dict[str, str]:
    """Map purification target -> Flow purification_agent string.

    Antibodies named in a sentence that also names the CLIP assay take precedence over
    antibodies named anywhere else in the Methods — papers routinely list a different
    antibody for Western blotting than for the IP, and only the assay sentence is
    authoritative for `Purification Agent`.
    """
    assay_hits: dict[str, str] = {}
    other_hits: dict[str, str] = {}

    for sentence in _sentences(text):
        bucket = assay_hits if ASSAY_SENTENCE_RE.search(sentence) else other_hits
        for match in ANTIBODY_METHODS_RE.finditer(sentence):
            target = match.group("target").upper()
            target = TARGET_ALIASES.get(target, target)
            vendor, catalog = split_vendor_catalog(match.group("inner"))
            if not vendor or not catalog:
                continue
            bucket.setdefault(
                target, _agent_string(match.group("species") or "", target, vendor, catalog)
            )

    agents = dict(other_hits)
    agents.update(assay_hits)
    return agents


def is_generic_purification_agent(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return True
    if value.lower() in ALLOWED_AGENT_LITERALS:
        return False
    return bool(GENERIC_AGENT_RE.match(value))


def _iclap_agent() -> str:
    return "Strep/His affinity tag purification"


def _resolve_purification_agent(
    row: dict[str, Any],
    antibodies: dict[str, str],
) -> tuple[str, str | None]:
    """Return (agent, warning_message)."""
    method = str(row.get("Experimental Method", "")).strip()
    protein = str(row.get("Protein (Purification Target)", "")).strip().upper()
    current = str(row.get("Purification Agent", "")).strip()

    if protein in SKIP_TARGETS or protein == "SMINPUT":
        return "no antibody", None
    if method.upper() == "ICLAP":
        return _iclap_agent(), None

    agent = antibodies.get(protein, "")
    if agent:
        return agent, None
    if current and not is_generic_purification_agent(current):
        return current, None
    if protein:
        return current, f"no paper antibody found for target {protein}"
    return current, "missing purification target; cannot resolve antibody"


def collect_annotation_field_warnings(df: pd.DataFrame) -> list[AnnotationWarning]:
    warnings: list[AnnotationWarning] = []
    # NB: "Purification Target Annotation" is deliberately NOT tracked for emptiness —
    # an endogenous IP legitimately has no tag. Its *grammar* is checked instead by
    # lib/metadata_validate.validate_target_and_annotation.
    tracked = (
        "Purification Agent",
        "Scientist",
        "PI",
        "PubMed ID",
        "Protein (Purification Target)",
        "5' Barcode Sequence",
        "Organism",
        "Cell or Tissue",
    )
    for idx, row in df.iterrows():
        sample = str(row.get("Sample Name", "")).strip()
        for field in tracked:
            val = str(row.get(field, "")).strip()
            if not val:
                warnings.append(
                    AnnotationWarning(
                        row=int(idx) + 2,
                        sample_name=sample,
                        field=field,
                        message="field is empty",
                    )
                )
            elif field == "Purification Agent" and is_generic_purification_agent(val):
                warnings.append(
                    AnnotationWarning(
                        row=int(idx) + 2,
                        sample_name=sample,
                        field=field,
                        message=f"generic or vague value: {val!r}",
                    )
                )
    return warnings


def enrich_annotation_from_paper(
    annotation: pd.DataFrame,
    pmid: str,
    *,
    paper_text: str = "",
) -> tuple[pd.DataFrame, PaperMetadata, list[AnnotationWarning]]:
    """Apply first-author Scientist, last-author PI, and paper-derived purification agents."""
    if annotation.empty or not str(pmid).strip():
        return annotation, PaperMetadata(pmid="", title="", authors=[], first_author="", last_author="", pmcid="", methods_text=""), []

    paper = load_paper_metadata(pmid, paper_text=paper_text)
    antibodies = extract_antibodies_from_text(paper.methods_text)
    enriched = annotation.copy()

    if paper.first_author:
        enriched["Scientist"] = paper.first_author
    if paper.last_author:
        enriched["PI"] = paper.last_author
    if paper.pmid:
        enriched["PubMed ID"] = paper.pmid

    row_warnings: list[AnnotationWarning] = []
    for idx, row in enriched.iterrows():
        row_dict = row.to_dict()
        agent, warn = _resolve_purification_agent(row_dict, antibodies)
        enriched.at[idx, "Purification Agent"] = agent
        if warn:
            row_warnings.append(
                AnnotationWarning(
                    row=int(idx) + 2,
                    sample_name=str(row_dict.get("Sample Name", "")),
                    field="Purification Agent",
                    message=warn,
                )
            )

    field_warnings = collect_annotation_field_warnings(enriched)
    # Drop duplicate generic-agent warnings when we already set a specific agent
    seen: set[tuple[str, str]] = set()
    merged: list[AnnotationWarning] = []
    for w in row_warnings + field_warnings:
        key = (w.sample_name, w.field)
        if w.field == "Purification Agent" and key in seen:
            continue
        if w.field == "Purification Agent" and w.message.startswith("generic"):
            val = str(enriched.loc[w.row - 2, "Purification Agent"])
            if val and not is_generic_purification_agent(val):
                continue
        seen.add(key)
        merged.append(w)
    return enriched, paper, merged


def write_annotation_warnings(
    output_dir: Path,
    warnings: list[AnnotationWarning],
    paper: PaperMetadata | None = None,
) -> Path:
    path = output_dir / "ANNOTATION_WARNINGS.md"
    lines = [
        "# Annotation field warnings",
        "",
        "Mandatory paper-metadata enrichment flagged the following gaps.",
        "",
    ]
    if paper and paper.pmid:
        lines += [
            f"**PMID:** [{paper.pmid}](https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/)",
            f"**Title:** {paper.title or '(unknown)'}",
            f"**First author (Scientist):** {paper.first_author or '(not resolved)'}",
            f"**Last author (PI):** {paper.last_author or '(not resolved)'}",
            f"**PMC:** {paper.pmcid or '(none)'}",
            "",
        ]
    if not warnings:
        lines.append("No warnings — all tracked fields populated with specific values.")
    else:
        lines += [
            "| Row | Sample | Field | Issue |",
            "|-----|--------|-------|-------|",
        ]
        for w in warnings:
            lines.append(f"| {w.row} | `{w.sample_name}` | {w.field} | {w.message} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    (output_dir / "annotation_warnings.json").write_text(
        json.dumps(
            {
                "paper": asdict(paper) if paper else {},
                "warnings": [asdict(w) for w in warnings],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
