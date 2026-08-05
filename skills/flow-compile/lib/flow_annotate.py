"""Stage 4: Flow upload annotation table (flow-annotate rules)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from lib.barcode_evidence import normalize_flow_barcode
from lib.barcode_resolver import BarcodeResolution
from lib.organism import normalize_organism, validate_organism_column
from lib.protein_target_annotation import infer_purification_target_annotation
from lib.sample_naming import build_flow_sample_name, validate_flow_sample_name

ANNOTATION_COLUMNS = [
    "File",
    "File 2",
    "Sample Name",
    "Project Name",
    "Scientist",
    "PI",
    "Organisation",
    "Purification Agent",
    "Experimental Method",
    "Condition",
    "Sequencer",
    "Comments",
    "5' Barcode Sequence",
    "3' Barcode Sequence",
    "GEO ID",
    "PubMed ID",
    "Type",
    "Cell or Tissue",
    "Organism",
    "Protein (Purification Target)",
    "Purification Target Annotation",
]


#: Cell lines that routinely lead a GEO title — never a purification target.
CELL_LINE_TOKENS = frozenset(
    {
        "HELA", "HEK293", "HEK293T", "293T", "HEK", "K562", "HEPG2", "MCF7", "U2OS",
        "SH-SY5Y", "SHSY5Y", "NIH3T3", "3T3", "JURKAT", "A549", "U87", "HCT116",
        "MEF", "ESC", "HESC", "MESC", "IPSC", "CCE", "2102EP", "H9",
    }
)
#: Antibody host species — `infer_protein_target` used to return these verbatim.
SPECIES_TOKENS = frozenset(
    {"RABBIT", "MOUSE", "GOAT", "RAT", "HUMAN", "SHEEP", "DONKEY", "CHICKEN", "LLAMA"}
)
#: Size-matched input / control markers. eCLIP inputs are their own target.
_INPUT_RE = re.compile(r"\b(sm[\s_-]?input|size[\s_-]?matched\s+input|input)\b", re.I)
_IGG_RE = re.compile(r"\b(igg|mock|beads?[\s_-]only|no[\s_-]antibody)\b", re.I)
#: A plausible gene symbol: starts with a letter, mostly alphanumeric, not too long.
_GENE_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-]{1,14}$")


def _is_plausible_target(token: str) -> bool:
    """Reject cell lines, host species and antibody fragments posing as gene symbols."""
    candidate = (token or "").strip().upper()
    if not candidate or not _GENE_SYMBOL_RE.match(candidate):
        return False
    if candidate in CELL_LINE_TOKENS or candidate in SPECIES_TOKENS:
        return False
    if candidate.startswith("ANTI"):
        return False
    return True


def infer_protein_target(title: str, characteristics: list[str] | None = None) -> str:
    title = title or ""
    # Controls first — an input row must never inherit the IP's protein.
    if _INPUT_RE.search(title):
        return "SMInput"
    if _IGG_RE.search(title):
        return "IgG"

    # GEO titles like "CPSF5, HEK293T, replicate 1 eCLIP"
    if "," in title:
        for field in title.split(","):
            lead = field.strip()
            if _is_plausible_target(lead):
                return lead.upper()
    upper_title = title.upper()
    if "GFP" in upper_title.split():
        return "GFP"
    if "IGG" in upper_title:
        return "IgG"
    match = re.search(
        r"\b(SRSF\d+|U2AF65|QKI|PTBP\d+|TDP-?43|HNRNP[A-Z0-9]+|DHX\d+)\b",
        title,
        re.I,
    )
    if match:
        return match.group(1).upper()
    iclip_target = re.search(r"iCLIP[-_]([A-Z0-9]+)", title, re.I)
    if iclip_target:
        return iclip_target.group(1).upper()
    tokens = title.replace("_", " ").split()
    for token in tokens:
        if re.match(r"^SRSF\d+$", token, re.I):
            return token.upper()
    for item in characteristics or []:
        lower = item.lower()
        if "antibody:" in lower or "purification" in lower:
            if ":" in item:
                agent = item.split(":", 1)[1].strip()
                # "rabbit anti-PARP13 (Thermo …)" — skip the host species and the
                # anti- prefix rather than returning RABBIT or ANTI-PARP13.
                for word in agent.replace("(", " ").split():
                    token = word.strip(",;()").upper()
                    if token.startswith("ANTI-") and _is_plausible_target(token[5:]):
                        return token[5:]
                    if _is_plausible_target(token):
                        return token
    return ""


def purification_agent(
    characteristics: list[str],
    *,
    extract_protocol: str = "",
    title: str = "",
) -> str:
    for item in characteristics:
        lower = item.lower()
        if ("purification" in lower or "antibody:" in lower or "clip antibody:" in lower) and ":" in item:
            return item.split(":", 1)[1].strip()
    proto = (extract_protocol or "").lower()
    if "v5-antibody" in proto or "v5 antibody" in proto:
        return "V5-antibody"
    if "immunoprecipitated with rbp specific" in proto:
        lead = (title or "").split(",", 1)[0].strip()
        if lead:
            return f"{lead} antibody"
    return ""


def _cell_from_characteristics(characteristics: list[str]) -> str:
    for item in characteristics:
        lower = item.lower()
        if lower.startswith("cell line:") or lower.startswith("cell type:"):
            return item.split(":", 1)[1].strip()
    return ""


def resolve_source(*, source_name: str, characteristics: list[str] | None) -> str:
    """Cell or tissue for the annotation sheet.

    An explicit `cell line:` / `cell type:` characteristic wins over
    `!Sample_source_name_ch1`, which is often a supplier phrase ("ATCC Cell Lines") or a
    generic descriptor ("human embryonic kidney") rather than the actual line.
    """
    return _cell_from_characteristics(characteristics or []) or (source_name or "").strip()


def build_sample_name(protein: str, cell: str, org: str, title: str, srr: str) -> str:
    return build_flow_sample_name(protein, cell, org, title, srr)


#: "cells were flash-frozen in liquid nitrogen" is boilerplate in extract protocols and
#: must not be read as the FLASH protocol.
_FLASH_FROZEN_RE = re.compile(r"flash[\s-]*fro(?:zen|ze)", re.I)

#: (regex, method) in specificity order. Word boundaries stop prose mentions misfiring.
_METHOD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\biclip2\b", re.I), "iCLIP2"),
    (re.compile(r"\bse[\s-]?clip\b", re.I), "seCLIP"),
    (re.compile(r"\buvclap\b", re.I), "uvCLAP"),
    (re.compile(r"\bpar[\s-]?clip\b", re.I), "PAR-CLIP"),
    (re.compile(r"\bhits[\s-]?clip\b", re.I), "HITS-CLIP"),
    (re.compile(r"\biclap\b", re.I), "iCLAP"),
    (re.compile(r"\bflash\b", re.I), "FLASH"),
    (re.compile(r"\beclip\b", re.I), "eCLIP"),
    (re.compile(r"\biclip\b", re.I), "iCLIP"),
]


def _match_method(text: str) -> str:
    blob = _FLASH_FROZEN_RE.sub(" ", text or "")
    for pattern, method in _METHOD_PATTERNS:
        if pattern.search(blob):
            return method
    return ""


def infer_experimental_method(protocol: str, series_title: str = "") -> str:
    """Resolve the CLIP protocol, preferring the series title over protocol prose.

    The title names the assay; extract protocols routinely cite *other* protocols
    ("as described for eCLIP…", "FLASH is a variant of iCLIP"), so matching the protocol
    blob first mislabels studies. `flash-frozen` is stripped before any FLASH match.

    Unknown protocols still fall back to iCLIP — the most common CLIP flavour — but that
    fallback is a guess and is surfaced in the metadata hook rather than trusted silently.
    """
    return _match_method(series_title) or _match_method(protocol) or "iCLIP"


def load_srr_map(path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    required = {"gsm", "srr", "mate", "fastq"}
    if not required.issubset(df.columns):
        raise ValueError(f"SRR map must contain columns: {sorted(required)}")
    return df


def is_eclip_method(method: str) -> bool:
    return (method or "").strip().lower() in {"eclip", "seclip"}


def _fastq_paths_for_gsm(
    srr_rows: pd.DataFrame,
    *,
    r1_only: bool = False,
) -> tuple[str, str]:
    """Return (reads1, reads2) paths for a GSM from srr_map rows."""
    rows = srr_rows.sort_values("mate")
    file1 = str(rows.iloc[0]["fastq"])
    file2 = ""
    if not r1_only:
        if "file2" in rows.columns and pd.notna(rows.iloc[0].get("file2")):
            file2 = str(rows.iloc[0]["file2"]).strip()
        elif len(rows) > 1:
            file2 = str(rows.iloc[1]["fastq"])
    return file1, file2


def apply_eclip_crosslink_mate_filenames(annotation: pd.DataFrame) -> pd.DataFrame:
    """eCLIP: upload the mate that carries the crosslink.

    Paired-end eCLIP puts the randomer on read 2's 5′ end and the crosslink immediately
    after it, so **read 2 is the crosslink read** — the Yeo pipeline extracts it with
    ``samtools view -f 128`` and ``eclipdemux`` trims the randomer from "the front of 2nd
    read in pair". Read 1 only carries the 7 nt inline demultiplexing barcode, which is
    not needed once multi-barcode libraries are merged.

    seCLIP is genuinely single-end: read 1 is the only read and already carries the
    crosslink, so there is nothing to promote.

    Non-eCLIP rows are left alone — iCLIP has its crosslink on read 1.

    See ``reference/eclip-analysis-params.md``.
    """
    updated = annotation.copy()
    if "File 2" not in updated.columns or "Experimental Method" not in updated.columns:
        return updated

    for index, row in updated.iterrows():
        if not is_eclip_method(str(row.get("Experimental Method", ""))):
            continue
        mate2 = str(row.get("File 2", "") or "").strip()
        if mate2:
            updated.at[index, "File"] = mate2
        updated.at[index, "File 2"] = ""
    return updated


def build_annotation_table(
    matrix_data: dict[str, Any],
    srr_map: pd.DataFrame,
    barcode_by_gsm: dict[str, BarcodeResolution],
    experimental_method: str | None = None,
) -> pd.DataFrame:
    series = matrix_data["series"]
    samples = matrix_data["samples"]
    project_name = series.get("title", "")
    pmid = series.get("pubmed_id", "")
    scientist = (series.get("contact_name", "") or "").replace(",,", " ").strip()
    pi = scientist.split()[-1] if scientist else ""
    organisation = series.get("contact_institute", "")

    protocol_blob = " ".join(
        str(s.get("extract_protocol_ch1", "")) for s in samples.values()
    )
    method = experimental_method or infer_experimental_method(protocol_blob, project_name)

    rows: list[dict[str, str]] = []
    for gsm, srr_rows in srr_map.groupby("gsm", sort=False):
        sample = samples.get(str(gsm))
        if sample is None:
            continue
        srr_rows = srr_rows.sort_values("mate")
        title = sample.get("title", "")
        cell = resolve_source(
            source_name=sample.get("source_name_ch1", ""),
            characteristics=sample.get("characteristics", []),
        )
        org = normalize_organism(sample.get("organism_ch1", ""))
        characteristics = sample.get("characteristics", [])
        protein = infer_protein_target(title, characteristics)
        barcode = barcode_by_gsm.get(str(gsm))
        srr = str(srr_rows.iloc[0]["srr"])
        sample_name = build_sample_name(protein, cell, org, title, srr)
        name_errors = validate_flow_sample_name(sample_name)
        if name_errors:
            raise ValueError(
                f"Invalid Flow sample name for {gsm} ({title!r}): "
                + "; ".join(name_errors)
            )

        # Keep both mates here; apply_eclip_crosslink_mate_filenames picks the
        # crosslink read (R2 for paired-end eCLIP) once the method is known.
        file1, file2 = _fastq_paths_for_gsm(srr_rows)
        row = {col: "" for col in ANNOTATION_COLUMNS}
        row["File"] = file1
        if file2:
            row["File 2"] = file2
        row["Sample Name"] = sample_name
        row["Project Name"] = project_name
        row["Scientist"] = scientist
        row["PI"] = pi
        row["Organisation"] = organisation
        row["Purification Agent"] = purification_agent(
            characteristics,
            extract_protocol=str(sample.get("extract_protocol_ch1", "")),
            title=title,
        )
        row["Experimental Method"] = method
        row["Sequencer"] = sample.get("instrument_model", "")
        row["5' Barcode Sequence"] = normalize_flow_barcode(barcode.five_prime) if barcode else ""
        row["3' Barcode Sequence"] = barcode.three_prime if barcode else ""
        row["GEO ID"] = gsm
        row["PubMed ID"] = pmid
        row["Type"] = "CLIP"
        row["Cell or Tissue"] = cell
        row["Organism"] = org
        row["Protein (Purification Target)"] = protein
        row["Purification Target Annotation"] = infer_purification_target_annotation(
            title=title,
            characteristics=characteristics,
            experimental_method=method,
            protein_target=protein,
            extract_protocol=str(sample.get("extract_protocol_ch1", "")),
        )
        rows.append(row)

    df = pd.DataFrame(rows, columns=ANNOTATION_COLUMNS)
    errors = validate_organism_column(df["Organism"].tolist())
    if errors:
        raise ValueError("Organism validation failed: " + "; ".join(errors))
    return df
