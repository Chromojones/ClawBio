"""Tests for eCLIP annotation (R1-only upload, GSE290281-style titles)."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.flow_annotate import (
    apply_eclip_r1_only_filenames,
    build_annotation_table,
    infer_protein_target,
    load_srr_map,
    purification_agent,
)
from lib.barcode_resolver import BarcodeResolution
from lib.geo_matrix import parse_geo_matrix
from lib.protein_target_annotation import infer_purification_target_annotation


GSE290281_MATRIX = Path(__file__).resolve().parents[5] / "GSE290281/geo/GSE290281_series_matrix.txt"
GSE290281_SRR = Path(__file__).resolve().parents[5] / "GSE290281/geo/srr_map.tsv"


class TestEclipAnnotate:
    def test_protein_from_comma_title(self):
        assert infer_protein_target("GRB2, HEK293T, IP, replicate 1 eCLIP") == "GRB2"

    def test_v5_purification_annotation(self):
        proto = (
            "Cells were lysed and immunoprecipitated with RBP specific or V5-antibody."
        )
        ann = infer_purification_target_annotation(
            title="CPSF5, HEK293T, IP, replicate 1 eCLIP",
            characteristics=["cell line: HEK293T"],
            experimental_method="eCLIP",
            protein_target="CPSF5",
            extract_protocol=proto,
        )
        assert ann == "cV5"
        agent = purification_agent(
            ["cell line: HEK293T"],
            extract_protocol=proto,
            title="CPSF5, HEK293T, IP, replicate 1 eCLIP",
        )
        assert agent == "V5-antibody"

    def test_apply_r1_only_clears_file2(self):
        df = pd.DataFrame({"File": ["SRR1_1.fastq.gz"], "File 2": ["SRR1_2.fastq.gz"]})
        out = apply_eclip_r1_only_filenames(df)
        assert out.iloc[0]["File 2"] == ""

    def test_build_annotation_omits_file2_for_eclip(self):
        if not GSE290281_MATRIX.exists():
            return
        matrix = parse_geo_matrix(GSE290281_MATRIX)
        srr_map = load_srr_map(GSE290281_SRR)
        barcode = BarcodeResolution(
            gsm="GSM8809678",
            five_prime="NNNNNNNNNN",
            three_prime="",
            protocol="eCLIP",
            confidence="confirmed",
        )
        ann = build_annotation_table(
            matrix,
            srr_map,
            {gsm: barcode for gsm in srr_map["gsm"].astype(str).unique()},
        )
        assert (ann["File 2"].fillna("") == "").all()
        assert ann.iloc[0]["Protein (Purification Target)"] == "CPSF5"
        assert ann.iloc[0]["Purification Target Annotation"] == "cV5"
