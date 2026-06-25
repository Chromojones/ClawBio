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
        if ("purification" in lower or "antibody:" in lower or "clip antibody:" in lower) and ":" in item:
            return item.split(":", 1)[1].strip()
    return ""


def _cell_from_characteristics(characteristics: list[str]) -> str:
    for item in characteristics:
        lower = item.lower()
        if lower.startswith("cell line:") or lower.startswith("cell type:"):
            return item.split(":", 1)[1].strip()
    return ""


def build_sample_name(protein: str, cell: str, org: str, title: str, srr: str) -> str:
    return build_flow_sample_name(protein, cell, org, title, srr)


def infer_experimental_method(protocol: str, series_title: str = "") -> str:
    blob = f"{protocol} {series_title}".lower()
    if "iclip2" in blob:
        return "iCLIP2"
    if "flash" in blob:
        return "FLASH"
    if "iclip" in blob:
        return "iCLIP"
    if "eclip" in blob:
        return "eCLIP"
    if "par-clip" in blob or "parclip" in blob:
        return "PAR-CLIP"
    if "uvclap" in blob:
        return "uvCLAP"
    return "iCLIP"


def load_srr_map(path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    required = {"gsm", "srr", "mate", "fastq"}
    if not required.issubset(df.columns):
        raise ValueError(f"SRR map must contain columns: {sorted(required)}")
    return df


def _fastq_paths_for_gsm(srr_rows: pd.DataFrame) -> tuple[str, str]:
    """Return (reads1, reads2) paths for a GSM from srr_map rows."""
    rows = srr_rows.sort_values("mate")
    file1 = str(rows.iloc[0]["fastq"])
    file2 = ""
    if "file2" in rows.columns and pd.notna(rows.iloc[0].get("file2")):
        file2 = str(rows.iloc[0]["file2"]).strip()
    elif len(rows) > 1:
        file2 = str(rows.iloc[1]["fastq"])
    return file1, file2


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
        cell = sample.get("source_name_ch1", "") or _cell_from_characteristics(
            sample.get("characteristics", [])
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
        row["Purification Agent"] = purification_agent(characteristics)
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
        )
        rows.append(row)

    df = pd.DataFrame(rows, columns=ANNOTATION_COLUMNS)
    errors = validate_organism_column(df["Organism"].tolist())
    if errors:
        raise ValueError("Organism validation failed: " + "; ".join(errors))
    return df
