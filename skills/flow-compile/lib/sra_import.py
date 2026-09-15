"""The accession sheet for `flowbio samples import`, written by `109_sheet`.

Accessions must be experiments (SRX/ERX/DRX): a run is silently expanded to its parent
experiment. `project` and `pubmed` are reserved columns (flowbio ≥ 0.12.0). `strandedness` is
refused for CLIP although `batch-template` lists it. Required: `accession`, `sample_type`,
`name`, `five_prime_barcode_sequence`, `purification_target`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from lib.import_check import RESERVED_SHEET_COLUMNS  # noqa: F401  (re-exported)
from lib.metadata_validate import normalize_annotation

#: `project` and `pubmed` became reserved here; below it they are swallowed as metadata.
MIN_FLOWBIO_VERSION = (0, 12, 0)

#: Columns that must never reach the import sheet, with why.
FORBIDDEN_SHEET_COLUMNS: dict[str, str] = {
    "strandedness": "RNA-Seq only; the CLIP import endpoint rejects it (422)",
    "reads1": "SRA-direct import has no local files",
    "reads2": "SRA-direct import has no local files",
}

_EXPERIMENT_RE = re.compile(r"^(SRX|ERX|DRX)\d+$", re.I)

#: annotation column -> import sheet column. Order defines the sheet's column order.
COLUMN_MAP: list[tuple[str, str]] = [
    ("Sample Name", "name"),
    ("Organism", "organism"),
    ("Experimental Method", "experimental_method"),
    ("Scientist", "scientist"),
    ("PI", "pi"),
    ("Organisation", "organisation"),
    ("Purification Agent", "purification_agent"),
    ("Protein (Purification Target)", "purification_target"),
    ("Purification Target Annotation", "purification_target__annotation"),
    ("Cell or Tissue", "source"),
    ("Source Annotation", "source__annotation"),
    ("Condition", "condition"),
    ("Sequencer", "sequencer"),
    ("5' Barcode Sequence", "five_prime_barcode_sequence"),
    ("3' Barcode Sequence", "three_prime_barcode_sequence"),
    ("GEO ID", "geo"),
    ("Comments", "comments"),
]

#: Flow rejects the whole import batch if any single `comments` value exceeds this.
#: Discovered on GSE76475: 11 rows refused because one was 1025 characters.
MAX_COMMENTS_CHARS = 1000

REQUIRED_CLIP_COLUMNS = (
    "accession",
    "sample_type",
    "name",
    "five_prime_barcode_sequence",
    "purification_target",
)


def is_experiment_accession(value: str) -> bool:
    """True for SRX/ERX/DRX experiment accessions (the only kind the import accepts)."""
    return bool(_EXPERIMENT_RE.match(str(value or "").strip()))


def _accession_for_row(row: pd.Series) -> str:
    for column in ("SRX", "srx", "Experiment", "ENA Experiment"):
        value = str(row.get(column, "") or "").strip()
        if value:
            return value
    return ""


def merge_srx_from_srr_map(annotation: pd.DataFrame, srr_map: pd.DataFrame) -> pd.DataFrame:
    """`build_import_sheet` requires an `SRX` column (see module docstring); `04_annotate`
    never writes one since `ANNOTATION_COLUMNS` is the Flow-facing biological schema, not a
    place for a download detail specific to the SRA-direct route. `srr_map.tsv` — the same
    file `109_sheet` is handed again — already carries `srx` per GSM
    (`reference/sra-direct-import.md`'s own column-mapping table: "(from srr_map.srx) ->
    accession"), keyed by the annotation's `GEO ID` column. Returns a copy; `annotation` is
    never mutated in place.
    """
    if "srx" not in srr_map.columns:
        return annotation
    gsm_to_srx = (
        srr_map.drop_duplicates("gsm").set_index("gsm")["srx"].astype(str).to_dict()
    )
    merged = annotation.copy()
    merged["SRX"] = merged["GEO ID"].map(gsm_to_srx).fillna("")
    return merged


def annotation_to_flow_row(row) -> dict[str, str]:
    """One annotation row in Flow's keys: what the sheet sends and what `11_verify` compares."""
    record: dict[str, str] = {}
    for source_col, target_col in COLUMN_MAP:
        if target_col in FORBIDDEN_SHEET_COLUMNS:
            continue
        value = str(row.get(source_col, "") or "").strip()
        if target_col == "purification_target__annotation":
            value = normalize_annotation(value)
        if value:
            record[target_col] = value
    return record


def build_import_sheet(
    annotation: pd.DataFrame,
    *,
    sample_type: str = "CLIP",
    project_id: str = "",
) -> pd.DataFrame:
    """Map an annotation table onto a flowbio accession sheet; empty optional columns are dropped.

    :raises ValueError: if any row lacks an SRX/ERX/DRX experiment accession.
    """
    if annotation is None or annotation.empty:
        return pd.DataFrame(columns=list(REQUIRED_CLIP_COLUMNS))

    records: list[dict[str, str]] = []
    for position, (_, row) in enumerate(annotation.iterrows(), start=1):
        accession = _accession_for_row(row)
        if not is_experiment_accession(accession):
            name = str(row.get("Sample Name", "")).strip() or f"row {position}"
            raise ValueError(
                f"{name}: {accession or '(missing)'!r} is not an experiment accession — "
                "flowbio samples import requires SRX/ERX/DRX. A run accession is ACCEPTED "
                "but silently expanded to its parent experiment: importing SRR3175580 "
                "produced one sample carrying all four runs of SRX1590001. The job reports "
                "COMPLETED, so the duplication surfaces nowhere. Populate the 'SRX' column "
                "of srr_map.tsv."
            )
        record: dict[str, str] = {"accession": accession, "sample_type": sample_type}
        # Reserved since 0.12.0. Omitted entirely when absent: an empty cell is sent as an
        # empty string, not treated as "unset".
        if project_id:
            record["project"] = str(project_id).strip()
        record.update(annotation_to_flow_row(row))
        records.append(record)

    sheet = pd.DataFrame(records)

    ordered = ["accession", "sample_type"] + (["project"] if "project" in sheet.columns else []) + [
        target for _, target in COLUMN_MAP if target in sheet.columns
    ]
    sheet = sheet[[c for c in ordered if c in sheet.columns]]

    for column in FORBIDDEN_SHEET_COLUMNS:
        if column in sheet.columns:
            sheet = sheet.drop(columns=[column])

    return validate_import_sheet(sheet)


def validate_import_sheet(sheet: pd.DataFrame) -> pd.DataFrame:
    """Refuse a sheet the import endpoint would reject. One bad row fails the whole batch, and the
    API names it only by position.
    """
    missing = [c for c in REQUIRED_CLIP_COLUMNS if c not in sheet.columns]
    if missing:
        raise ValueError(
            f"import sheet missing required column(s): {', '.join(missing)} — "
            "CLIP imports require accession, sample_type, name, "
            "five_prime_barcode_sequence and purification_target"
        )

    if "comments" in sheet.columns:
        # Comments are where this skill records the evidence behind every judgement call, so
        # they grow naturally. Truncating would silently discard provenance — fail loudly and
        # name the rows so the author decides what to cut.
        over = [
            f"{row.get('name', f'row {position}')} ({len(str(row['comments']))} chars)"
            for position, (_, row) in enumerate(sheet.iterrows(), start=1)
            if len(str(row.get("comments") or "")) > MAX_COMMENTS_CHARS
        ]
        if over:
            raise ValueError(
                f"comments exceed Flow's {MAX_COMMENTS_CHARS}-character limit for: "
                f"{'; '.join(over)} — shorten them; one long row rejects the entire import"
            )
    return sheet


def write_import_sheet(output_dir: Path, sheet: pd.DataFrame) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "import_sheet.csv"
    sheet.to_csv(path, index=False)
    return path


