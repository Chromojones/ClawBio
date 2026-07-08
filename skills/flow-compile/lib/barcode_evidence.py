"""Extract barcode evidence from paper methods, GEO pages, and pipeline text."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

BARCODE_TRIM_BP = re.compile(
    r"barcode\s+trim(?:ming)?\s*\([^)]*?first\s+(\d+)\s+bp",
    re.I,
)
BARCODE_UMI_LENGTHS = re.compile(
    r"(\d+)\s+bp\s+barcode(?:\s+and\s+|\s*\+\s*)(\d+)\s+bp\s+(?:UMI|umi)",
    re.I,
)
MIN_READ_BARCODE_UMI = re.compile(
    r"min(?:imum)?\.?\s+read\s+length\s+of\s+(\d+)\s+bp\s+includes\s+(\d+)\s+bp\s+barcode\s+and\s+(\d+)\s+bp\s+(?:UMI|umi)\s+regions",
    re.I,
)
LITERAL_BARCODE_PARENS = re.compile(r"barcodes?\s*\(\s*([ACGTN]+)\s+and\s+([ACGTN]+)\s*\)", re.I)
ADAPTER_SEQ = re.compile(r"adapter-seq\s+([ACGTN]+)", re.I)
ICLIP2_REF = re.compile(r"PMID:\s*31610236|iclip2", re.I)


@dataclass
class BarcodeEvidence:
    source: str
    quote: str
    kind: str
    five_prime_proposal: str = ""
    umi_proposal: str = ""
    barcode_bp: int | None = None
    umi_bp: int | None = None
    confidence: str = "medium"
    notes: str = ""


@dataclass
class BarcodeProposal:
    gsm: str
    five_prime: str
    umi_barcode: str
    protocol: str
    confidence: str
    status: str  # pending_confirmation | confirmed | rejected
    evidence: list[BarcodeEvidence] = field(default_factory=list)
    agent_notes: str = ""


FLOW_BARCODE_CHARS = frozenset("ACGTN")


def _n_mers(length: int) -> str:
    return "N" * length if length > 0 else ""


def normalize_flow_barcode(pattern: str) -> str:
    """
    Flow upload metadata allows only A, C, G, T, N in 5' barcode sequences.
    Map FLASH/IUPAC grammar symbols (R, Y, B) and any other non-ACGTN character to N.
    """
    if not pattern:
        return ""
    return "".join(ch if ch in FLOW_BARCODE_CHARS else "N" for ch in pattern.upper())


def extract_evidence_from_text(text: str, source: str) -> list[BarcodeEvidence]:
    """Deterministic extraction from methods / GEO / data_processing prose."""
    evidence: list[BarcodeEvidence] = []
    if not text:
        return evidence

    for match in BARCODE_TRIM_BP.finditer(text):
        bp = int(match.group(1))
        evidence.append(
            BarcodeEvidence(
                source=source,
                quote=match.group(0)[:240],
                kind="geo_barcode_trim_bp",
                five_prime_proposal=_n_mers(bp),
                barcode_bp=bp,
                confidence="high",
            )
        )

    for match in BARCODE_UMI_LENGTHS.finditer(text):
        bbp, ubp = int(match.group(1)), int(match.group(2))
        evidence.append(
            BarcodeEvidence(
                source=source,
                quote=match.group(0)[:240],
                kind="barcode_umi_lengths",
                five_prime_proposal=_n_mers(bbp),
                umi_proposal=_n_mers(ubp),
                barcode_bp=bbp,
                umi_bp=ubp,
                confidence="high",
            )
        )

    for match in MIN_READ_BARCODE_UMI.finditer(text):
        bbp, ubp = int(match.group(2)), int(match.group(3))
        evidence.append(
            BarcodeEvidence(
                source=source,
                quote=match.group(0)[:240],
                kind="min_read_barcode_umi",
                five_prime_proposal=_n_mers(bbp),
                umi_proposal=_n_mers(ubp),
                barcode_bp=bbp,
                umi_bp=ubp,
                confidence="high",
            )
        )

    for match in LITERAL_BARCODE_PARENS.finditer(text):
        b1, b2 = match.group(1).upper(), match.group(2).upper()
        evidence.append(
            BarcodeEvidence(
                source=source,
                quote=match.group(0)[:200],
                kind="literal_barcode",
                five_prime_proposal=b1,
                confidence="high",
                notes=f"alternate demux barcode: {b2}",
            )
        )

    for match in ADAPTER_SEQ.finditer(text):
        evidence.append(
            BarcodeEvidence(
                source=source,
                quote=match.group(0)[:120],
                kind="flexbar_adapter",
                five_prime_proposal="",
                confidence="low",
                notes="3' Illumina adapter — usually not the Flow 5' barcode field",
            )
        )

    if ICLIP2_REF.search(text):
        evidence.append(
            BarcodeEvidence(
                source=source,
                quote="iCLIP2 protocol reference (PMID 31610236)",
                kind="protocol_iclip2",
                confidence="medium",
            )
        )

    return evidence


def evidence_from_matrix_hints(hints: list[str], gsm: str) -> list[BarcodeEvidence]:
    """Turn geo_matrix.scan_barcode_patterns hits into ranked evidence."""
    out: list[BarcodeEvidence] = []
    for pat in hints:
        out.append(
            BarcodeEvidence(
                source=f"geo_matrix:{gsm}",
                quote=pat,
                kind="geo_matrix_literal",
                five_prime_proposal=normalize_flow_barcode(pat),
                confidence="medium",
                notes="Literal N/A/C/G/T pattern found in GEO series matrix cell text",
            )
        )
    return out


def evidence_from_replicate_cores(cores: list[str], gsm: str) -> list[BarcodeEvidence]:
    """Fixed 4-mer cores from supplementary filenames — replicate variant hints, not full patterns."""
    out: list[BarcodeEvidence] = []
    for core in cores:
        out.append(
            BarcodeEvidence(
                source=f"geo_matrix:{gsm}",
                quote=core,
                kind="geo_matrix_replicate_core",
                five_prime_proposal="",
                confidence="medium",
                notes=(
                    "Fixed 4-mer in supplementary filename — likely identifies which paper barcode "
                    "variant applies to this replicate (map core as substring of full NNN… pattern)"
                ),
            )
        )
    return out


def merge_proposal_from_evidence(gsm: str, evidence: list[BarcodeEvidence]) -> BarcodeProposal:
    """Pick best five_prime / UMI from ranked evidence. Status pending until human confirms."""
    protocol = "iclip2" if any(e.kind == "protocol_iclip2" for e in evidence) else "generic"

    kind_rank = {
        "geo_barcode_trim_bp": 0,
        "min_read_barcode_umi": 1,
        "barcode_umi_lengths": 2,
        "literal_barcode": 3,
        "geo_matrix_literal": 4,
        "protocol_iclip2": 9,
        "flexbar_adapter": 10,
    }
    conf_rank = {"high": 0, "medium": 1, "low": 2}

    ranked = sorted(
        evidence,
        key=lambda e: (kind_rank.get(e.kind, 5), conf_rank.get(e.confidence, 3)),
    )

    five_prime = ""
    umi = ""
    confidence = "low"
    for ev in ranked:
        if not five_prime and ev.five_prime_proposal:
            five_prime = ev.five_prime_proposal
            confidence = ev.confidence
        if not umi and ev.umi_proposal:
            umi = ev.umi_proposal

    if five_prime and umi and protocol == "iclip2":
        agent_notes = (
            f"GEO Data processing gives {len(five_prime)} bp barcode + {len(umi)} bp UMI as separate "
            f"regions (not a single {len(five_prime) + len(umi)} bp run — that combined length is "
            "unusually long for a 5' barcode field and is general domain knowledge, not something "
            "verifiable from FASTQ, since random N bases give no visible boundary between barcode "
            f"and UMI on the read). Agent's best guess: 5' Barcode Sequence = {five_prime} "
            f"({len(five_prime)}N) using the barcode-only length from GEO. Present this reasoning "
            "plus the exact quote in CONFIRM_BARCODES.md; user confirms or overrides."
        )
    elif five_prime:
        top = next((e for e in ranked if e.five_prime_proposal == five_prime), ranked[0] if ranked else None)
        agent_notes = f"Proposal from {top.kind if top else 'evidence'} ({top.source if top else ''})."
    else:
        agent_notes = (
            "NEEDS_USER_INPUT — no barcode proposal from GEO matrix, GEO sample pages, or paper text. "
            "Agent must search referenced publications or ask the user; do not invent a pattern."
        )

    five_prime = normalize_flow_barcode(five_prime)
    umi = normalize_flow_barcode(umi)

    return BarcodeProposal(
        gsm=gsm,
        five_prime=five_prime,
        umi_barcode=umi,
        protocol=protocol,
        confidence=confidence,
        status="pending_confirmation",
        evidence=evidence,
        agent_notes=agent_notes,
    )


def proposal_to_dict(proposal: BarcodeProposal) -> dict:
    d = asdict(proposal)
    d["evidence"] = [asdict(e) for e in proposal.evidence]
    return d


def load_confirmed_proposals(path) -> dict[str, BarcodeProposal]:
    import json
    from pathlib import Path

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, BarcodeProposal] = {}
    for item in data.get("proposals", []):
        if item.get("status") != "confirmed":
            continue
        ev = [BarcodeEvidence(**e) for e in item.get("evidence", [])]
        out[item["gsm"]] = BarcodeProposal(
            gsm=item["gsm"],
            five_prime=normalize_flow_barcode(item["five_prime"]),
            umi_barcode=normalize_flow_barcode(item.get("umi_barcode", "")),
            protocol=item.get("protocol", "generic"),
            confidence=item.get("confidence", "high"),
            status="confirmed",
            evidence=ev,
            agent_notes=item.get("agent_notes", ""),
        )
    return out
