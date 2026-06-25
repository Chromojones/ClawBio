"""Tests for purification target annotation inference."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.protein_target_annotation import infer_purification_target_annotation


class TestPurificationTargetAnnotation:
    def test_uvclap_hdhx9_flag(self):
        ann = infer_purification_target_annotation(
            title="F1 hDHX9 repA",
            characteristics=[
                "cell line: HEK293",
                "expression vector: hDHX9",
                "clip antibody: Anti-FLAG M2 Magnetic Beads (M8823 Sigma)",
            ],
            experimental_method="uvCLAP",
            protein_target="DHX9",
        )
        assert ann == "c3xFLAG-HBH"

    def test_flashendo_dhx9_no_tag(self):
        ann = infer_purification_target_annotation(
            title="XL1 DHX9-mAb repA",
            characteristics=[
                "cell line: HEK293",
                "clip antibody: DHX9-mAb",
            ],
            experimental_method="FLASH",
            protein_target="DHX9",
        )
        assert ann == ""

    def test_gfp_control_vector_only(self):
        ann = infer_purification_target_annotation(
            title="G1 control repA",
            characteristics=[
                "cell line: HEK293",
                "expression vector: HBH tag",
                "clip antibody: Anti-FLAG M2 Magnetic Beads",
            ],
            experimental_method="uvCLAP",
            protein_target="",
        )
        assert ann == ""
