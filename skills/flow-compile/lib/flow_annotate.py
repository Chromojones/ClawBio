"""Stage 4: Flow upload annotation table (flow-annotate rules)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from lib.barcode_resolver import BarcodeResolution
from lib.organism import normalize_organism, validate_organism_column

ANNOTATION_COLUMNS = [
    "File",
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
]


def infer_protein_target(title: str, characteristics: list[str] | None = None) -> str:
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
                if agent:
                    return agent.split()[0].upper()
    return ""


def purification_agent(characteristics: list[str]) -> str:
    for item in characteristics:
        lower = item.lower()
        if ("purification" in lower or "antibody:" in lower) and ":" in item:
            return item.split(":", 1)[1].strip()
    return ""


def build_sample_name(protein: str, cell: str, org: str, title: str, srr: str) -> str:
    rep = "Rep2" if "rep2" in title.lower() else "Rep1"
    parts = [p for p in [protein, org, cell, rep, srr] if p]
    return "_".join(parts)


def infer_experimental_method(protocol: str, series_title: str = "") -> str:
    blob = f"{protocol} {series_title}".lower()
    if "iclip2" in blob:
        return "iCLIP2"
    if "iclip" in blob or "flash" in blob:
        return "iCLIP"
    if "eclip" in blob:
        return "eCLIP"
    if "par-clip" in blob or "parclip" in blob:
        return "PAR-CLIP"
    return "iCLIP"


def load_srr_map(path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    required = {"gsm", "srr", "mate", "fastq"}
    if not required.issubset(df.columns):
        raise ValueError(f"SRR map must contain columns: {sorted(required)}")
    return df


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
    for _, srr_row in srr_map.iterrows():
        gsm = str(srr_row["gsm"])
        sample = samples.get(gsm)
        if not sample:
            continue
        title = sample.get("title", "")
        cell = sample.get("source_name_ch1", "")
        org = normalize_organism(sample.get("organism_ch1", ""))
        characteristics = sample.get("characteristics", [])
        protein = infer_protein_target(title, characteristics)
        barcode = barcode_by_gsm.get(gsm)
        srr = str(srr_row["srr"])
        sample_name = build_sample_name(protein, cell, org, title, srr)

        row = {col: "" for col in ANNOTATION_COLUMNS}
        row["File"] = str(srr_row["fastq"])
        row["Sample Name"] = sample_name
        row["Project Name"] = project_name
        row["Scientist"] = scientist
        row["PI"] = pi
        row["Organisation"] = organisation
        row["Purification Agent"] = purification_agent(characteristics)
        row["Experimental Method"] = method
        row["Sequencer"] = sample.get("instrument_model", "")
        row["5' Barcode Sequence"] = barcode.five_prime if barcode else ""
        row["3' Barcode Sequence"] = barcode.three_prime if barcode else ""
        row["GEO ID"] = gsm
        row["PubMed ID"] = pmid
        row["Type"] = "CLIP"
        row["Cell or Tissue"] = cell
        row["Organism"] = org
        row["Protein (Purification Target)"] = protein
        rows.append(row)

    df = pd.DataFrame(rows, columns=ANNOTATION_COLUMNS)
    errors = validate_organism_column(df["Organism"].tolist())
    if errors:
        raise ValueError("Organism validation failed: " + "; ".join(errors))
    return df
