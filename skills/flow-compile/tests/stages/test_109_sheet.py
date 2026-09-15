"""109_sheet must resolve an SRX experiment accession for every row on the SRA-direct line.

`build_import_sheet` requires an `SRX` column on the annotation it is given (tests/unit/
test_sra_import.py constructs that column by hand), but `04_annotate`'s `build_annotation_table`
never writes one — `ANNOTATION_COLUMNS` has no SRX/SRX-like field, only the Flow-facing
biological columns. GSE149561 hit this live: `annotation.raw.csv` has no SRX, so every row
raised "'(missing)' is not an experiment accession" even though `srr_map.tsv` (used to build
the annotation) already carries `srx` per `reference/sra-direct-import.md`'s own column-mapping
table ("(from `srr_map.srx`) -> accession"). 109_sheet needs the same `srr_map.tsv` again to
merge that column in before building the sheet.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import state as st  # noqa: E402
from lib.flow_annotate import ANNOTATION_COLUMNS  # noqa: E402


def _stage_module():
    spec = importlib.util.spec_from_file_location(
        "stage_109", SKILL_DIR / "stages" / "109_sheet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_dir(tmp_path):
    """A run past Gate 3, with an annotation carrying no SRX — 04_annotate's real shape."""
    out = tmp_path / "run"
    out.mkdir()
    st.record(out, "108_params", st.OK)
    st.set_study(out, accession="GSE149561", project_id="805853231098302364")

    row = {col: "" for col in ANNOTATION_COLUMNS}
    row.update({
        "File": "SRR11638451.fastq.gz",
        "Sample Name": "SYNCRIP_Rn_primary_cortical_neurons_Rep1_SRR11638451",
        "5' Barcode Sequence": "NNNGGTTNN",
        "GEO ID": "GSM4504851",
        "Protein (Purification Target)": "SYNCRIP",
        "Organism": "Rn",
        "Experimental Method": "iCLIP",
    })
    row2 = {col: "" for col in ANNOTATION_COLUMNS}
    row2.update({
        "File": "SRR11638452.fastq.gz",
        "Sample Name": "IgG_Rn_primary_cortical_neurons_Rep1_SRR11638452",
        "5' Barcode Sequence": "NNNTTGTNN",
        "GEO ID": "GSM4504852",
        "Protein (Purification Target)": "IgG",
        "Organism": "Rn",
        "Experimental Method": "iCLIP",
    })
    pd.DataFrame([row, row2], columns=ANNOTATION_COLUMNS).to_csv(
        out / "annotation.raw.csv", index=False)

    srr_map = out / "srr_map.tsv"
    srr_map.write_text(
        "gsm\tsrr\tsrx\n"
        "GSM4504851\tSRR11638451\tSRX8202282\n"
        "GSM4504852\tSRR11638452\tSRX8202283\n"
    )
    return out


def test_without_srr_map_the_missing_accession_error_still_names_the_cause(run_dir):
    """No regression: the guard from FAILURES.md#import-guards still fires when nothing
    supplies an SRX.
    """
    code = _stage_module().main(["--output", str(run_dir)])
    assert code != 0


def test_srr_map_supplies_the_srx_every_row_needs(run_dir):
    code = _stage_module().main([
        "--output", str(run_dir),
        "--srr-map", str(run_dir / "srr_map.tsv"),
    ])
    assert code == 0
    sheet = pd.read_csv(run_dir / "import_sheet.csv", dtype=str)
    accessions = dict(zip(sheet["name"], sheet["accession"]))
    assert accessions["SYNCRIP_Rn_primary_cortical_neurons_Rep1_SRR11638451"] == "SRX8202282"
    assert accessions["IgG_Rn_primary_cortical_neurons_Rep1_SRR11638452"] == "SRX8202283"
