"""Write Flow upload annotation XLSX from the annotation DataFrame."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_annotation_xlsx(
    annotation: pd.DataFrame,
    output_path: Path,
    *,
    sheet_name: str = "Sheet1",
) -> Path:
    """
    Export annotation table for uploadsample_flowbio_v6.py (--input-xlsx).

    Uses openpyxl engine; column headers match flow_annotate.ANNOTATION_COLUMNS.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        annotation.to_excel(writer, sheet_name=sheet_name, index=False)
    return output_path
