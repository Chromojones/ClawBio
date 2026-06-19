"""Stage 1: PubMed alert scan via pubmed-summariser's pubmed_api."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

CLIP_ALERT_QUERY = (
    '"crosslinking and immunoprecipitation"[Title/Abstract] AND '
    '(CLIP[Title/Abstract] OR iCLIP OR eCLIP OR "PAR-CLIP" OR FLASH OR "HITS-CLIP")'
)

CLIP_TERMS = re.compile(
    r"\b(iclip2?|eclip|par-?clip|clip-seq|hits-clip|flash|crosslinking)\b",
    re.I,
)
ACCESSION_RE = re.compile(r"\b(GSE\d+|SRP\d+|GSM\d+|SRR\d+)\b")


def _import_pubmed_api():
    pubmed_dir = Path(__file__).resolve().parent.parent.parent / "pubmed-summariser"
    if str(pubmed_dir) not in sys.path:
        sys.path.insert(0, str(pubmed_dir))
    import pubmed_api  # noqa: WPS433

    return pubmed_api


def extract_accessions(text: str) -> dict[str, list[str]]:
    found = ACCESSION_RE.findall(text or "")
    return {
        "gse": sorted({x for x in found if x.startswith("GSE")}),
        "srp": sorted({x for x in found if x.startswith("SRP")}),
        "gsm": sorted({x for x in found if x.startswith("GSM")}),
        "srr": sorted({x for x in found if x.startswith("SRR")}),
    }


def score_clip_paper(paper: dict[str, Any]) -> tuple[float, list[str]]:
    """Score 0–1 for CLIP relevance; return matched modality terms."""
    blob = " ".join(
        paper.get(k, "") or "" for k in ("title", "abstract")
    )
    modalities = sorted(set(m.lower() for m in CLIP_TERMS.findall(blob)))
    score = 0.0
    if modalities:
        score += 0.5
    if "crosslinking" in blob.lower() or "immunoprecipitation" in blob.lower():
        score += 0.2
    acc = extract_accessions(blob)
    if acc["gse"] or acc["srp"]:
        score += 0.3
    return min(1.0, score), modalities


def flag_clip_papers(papers: list[dict[str, Any]], min_score: float = 0.5) -> list[dict[str, Any]]:
    flagged: list[dict[str, Any]] = []
    for paper in papers:
        score, modalities = score_clip_paper(paper)
        if score < min_score:
            continue
        acc = extract_accessions(
            f"{paper.get('title', '')} {paper.get('abstract', '')}"
        )
        flagged.append(
            {
                "pmid": paper.get("pmid"),
                "title": paper.get("title"),
                "clip_score": round(score, 2),
                "modalities": modalities,
                "gse": acc["gse"],
                "srp": acc["srp"],
                "url": paper.get("url"),
                "status": "flagged_clip",
            }
        )
    return flagged


def run_pubmed_stage(
    output_dir: Path,
    query: str | None = None,
    max_results: int = 20,
    use_cache: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Fetch papers via pubmed-summariser API, flag CLIP hits, write stage artifacts.

    Returns (all_papers, flagged_clip_papers).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = output_dir / "stages" / "pubmed-summariser"
    stage_dir.mkdir(parents=True, exist_ok=True)

    if use_cache and use_cache.exists():
        papers = json.loads(use_cache.read_text(encoding="utf-8"))
    else:
        pubmed_api = _import_pubmed_api()
        papers = pubmed_api.fetch_papers(query or CLIP_ALERT_QUERY, max_results)

    (stage_dir / "papers.json").write_text(json.dumps(papers, indent=2))
    flagged = flag_clip_papers(papers)
    (stage_dir / "flagged_clip.json").write_text(json.dumps(flagged, indent=2))

    # Pointer for agents — full HTML briefing is optional via pubmed-summariser CLI
    (stage_dir / "README.txt").write_text(
        "Papers fetched via skills/pubmed-summariser/pubmed_api.py.\n"
        "For HTML briefing: python skills/pubmed-summariser/pubmed_summariser.py "
        f"--query {json.dumps(query or CLIP_ALERT_QUERY)} --output <dir>\n"
    )
    return papers, flagged
