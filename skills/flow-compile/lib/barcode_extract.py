"""Agent-assisted barcode extraction with human confirmation gate."""

from __future__ import annotations

import json
from pathlib import Path

from lib.barcode_evidence import (
    BarcodeProposal,
    extract_evidence_from_text,
    merge_proposal_from_evidence,
    proposal_to_dict,
)
from lib.geo_sample_fetch import load_geo_sample_text, strip_html


def render_confirmation_md(proposals: list[BarcodeProposal], output_dir: Path) -> str:
    lines = [
        "# Barcode proposals — human confirmation required",
        "",
        "Review each proposal. Edit `barcode_proposals.json` and set `status` to `confirmed`",
        "for rows you accept, then re-run with `--accept-proposals barcode_proposals.json`.",
        "",
        "| GSM | 5' proposal | UMI | Confidence | Status |",
        "|-----|-------------|-----|------------|--------|",
    ]
    for p in proposals:
        lines.append(
            f"| {p.gsm} | `{p.five_prime}` | `{p.umi_barcode}` | {p.confidence} | {p.status} |"
        )
    lines.extend(["", "## Evidence", ""])
    for p in proposals:
        lines.append(f"### {p.gsm}")
        lines.append(f"- **Agent notes:** {p.agent_notes}")
        for ev in p.evidence:
            lines.append(f"- `{ev.kind}` ({ev.confidence}) — {ev.quote[:120]}…")
        lines.append("")
    lines.append("*Do not upload until all required GSMs are confirmed.*")
    return "\n".join(lines) + "\n"


def extract_barcodes_for_gsms(
    gsms: list[str],
    *,
    paper_texts: list[tuple[str, Path]] | None = None,
    geo_cache_dir: Path | None = None,
    fetch_geo: bool = False,
) -> list[BarcodeProposal]:
    """Gather evidence from paper files + GEO; return pending proposals."""
    paper_texts = paper_texts or []
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

        proposals.append(merge_proposal_from_evidence(gsm, evidence))

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
