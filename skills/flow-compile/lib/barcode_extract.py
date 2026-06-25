"""Agent-assisted barcode extraction with human confirmation gate."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lib.barcode_evidence import (
    BarcodeProposal,
    extract_evidence_from_text,
    merge_proposal_from_evidence,
    normalize_flow_barcode,
    proposal_to_dict,
)
from lib.geo_sample_fetch import load_geo_sample_text, strip_html
from lib.sample_naming import infer_replicate_number


def assign_flash_replicate_barcode(proposal: BarcodeProposal, sample_title: str) -> BarcodeProposal:
    """FLASH XL libraries: RR = repA, YY = repB in RY-space barcode positions (GEO + PMC7026646)."""
    title = (sample_title or "").lower()
    if re.search(r"rep\s*a", title):
        biological = "NNRRNTTTTTTNN"
        proposal.five_prime = normalize_flow_barcode(biological)
        proposal.agent_notes = (
            "FLASH repA: biological RY-space pattern "
            f"`{biological}` → Flow metadata `{proposal.five_prime}` (R/Y/B→N). "
            "Confirm condition T-tags (T1–T6) from PMC7026646 Supplementary Table S1."
        )
        proposal.confidence = "medium"
    elif re.search(r"rep\s*b", title):
        biological = "NNYYNTTTTTTNN"
        proposal.five_prime = normalize_flow_barcode(biological)
        proposal.agent_notes = (
            "FLASH repB: biological RY-space pattern "
            f"`{biological}` → Flow metadata `{proposal.five_prime}` (R/Y/B→N). "
            "Confirm condition T-tags (T1–T6) from PMC7026646 Supplementary Table S1."
        )
        proposal.confidence = "medium"
    return proposal


def assign_per_sample_literal_barcode(proposal: BarcodeProposal, sample_title: str) -> BarcodeProposal:
    """When paper lists paired barcodes, assign by replicate number from GEO title."""
    rep_num = infer_replicate_number(sample_title)
    for ev in proposal.evidence:
        if ev.kind != "literal_barcode" or not ev.notes.startswith("alternate demux barcode:"):
            continue
        alternate = ev.notes.split(":", 1)[1].strip()
        if rep_num >= 2 and alternate:
            proposal.five_prime = alternate
            proposal.agent_notes = (
                f"Rep{rep_num} assigned alternate barcode `{alternate}` from {ev.source}."
            )
        elif rep_num == 1 and ev.five_prime_proposal:
            proposal.five_prime = ev.five_prime_proposal
            proposal.agent_notes = (
                f"Rep1 assigned barcode `{ev.five_prime_proposal}` from {ev.source}."
            )
        break
    return proposal


def render_confirmation_md(proposals: list[BarcodeProposal], output_dir: Path) -> str:
    lines = [
        "# Barcode hook — agent review required",
        "",
        "The agent should present this table, cite each **source**, and pause until the user confirms.",
        "Edit `barcode_proposals.json` (`status: confirmed`) then re-run with `--accept-proposals`.",
        "",
        "| GSM | 5' proposal | UMI | Source | Confidence | Status |",
        "|-----|-------------|-----|--------|------------|--------|",
    ]
    for p in proposals:
        sources = ", ".join(sorted({e.source for e in p.evidence})) or "—"
        lines.append(
            f"| {p.gsm} | `{p.five_prime}` | `{p.umi_barcode}` | {sources} | {p.confidence} | {p.status} |"
        )
    lines.extend(["", "## Evidence by GSM", ""])
    for p in proposals:
        lines.append(f"### {p.gsm}")
        lines.append(f"- **Agent notes:** {p.agent_notes}")
        if not p.evidence:
            lines.append("- _(no evidence extracted — add paper/GEO text)_")
        for ev in p.evidence:
            lines.append(
                f"- **{ev.kind}** ({ev.confidence}) — source: `{ev.source}` — \"{ev.quote[:160]}\""
            )
            if ev.notes:
                lines.append(f"  - note: {ev.notes}")
        lines.append("")
    lines.append("*Do not upload until all required GSMs are confirmed.*")
    return "\n".join(lines) + "\n"


def extract_barcodes_for_gsms(
    gsms: list[str],
    *,
    paper_texts: list[tuple[str, Path]] | None = None,
    geo_cache_dir: Path | None = None,
    fetch_geo: bool = False,
    sample_titles: dict[str, str] | None = None,
) -> list[BarcodeProposal]:
    """Gather evidence from paper files + GEO; return pending proposals."""
    paper_texts = paper_texts or []
    sample_titles = sample_titles or {}
    proposals: list[BarcodeProposal] = []

    shared_paper_evidence = []
    for label, path in paper_texts:
        text = path.read_text(encoding="utf-8", errors="replace")
        shared_paper_evidence.extend(extract_evidence_from_text(text, label))

    for gsm in gsms:
        evidence = list(shared_paper_evidence)
        cache = (geo_cache_dir / f"geo_{gsm}.txt") if geo_cache_dir else None
        if fetch_geo or (cache and cache.exists()):
            raw, source = load_geo_sample_text(gsm, cache_path=cache if cache else None)
            plain = strip_html(raw) if "<html" in raw.lower() else raw
            evidence.extend(extract_evidence_from_text(plain, source))
        elif cache and cache.exists():
            plain = cache.read_text(encoding="utf-8", errors="replace")
            evidence.extend(extract_evidence_from_text(plain, f"cache:{cache.name}"))

        proposals.append(
            assign_flash_replicate_barcode(
                assign_per_sample_literal_barcode(
                    merge_proposal_from_evidence(gsm, evidence),
                    sample_titles.get(gsm, ""),
                ),
                sample_titles.get(gsm, ""),
            )
        )

    return proposals


def write_proposal_bundle(output_dir: Path, proposals: list[BarcodeProposal]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "barcode_proposals.json"
    payload = {
        "status": "pending_confirmation",
        "proposals": [proposal_to_dict(p) for p in proposals],
    }
    path.write_text(json.dumps(payload, indent=2))
    (output_dir / "CONFIRM_BARCODES.md").write_text(render_confirmation_md(proposals, output_dir))
    return path


def all_confirmed(proposals: list[BarcodeProposal]) -> bool:
    return bool(proposals) and all(p.status == "confirmed" for p in proposals)


def apply_confirmed_to_resolutions(proposals: list[BarcodeProposal]):
    """Convert confirmed proposals to BarcodeResolution-like dicts for annotate stage."""
    from lib.barcode_resolver import BarcodeResolution

    out: list[BarcodeResolution] = []
    for p in proposals:
        if p.status != "confirmed":
            continue
        out.append(
            BarcodeResolution(
                gsm=p.gsm,
                five_prime=p.five_prime,
                three_prime=p.umi_barcode,
                protocol=p.protocol,
                confidence="high",
                sources=[e.kind for e in p.evidence],
                notes=p.agent_notes,
            )
        )
    return out
