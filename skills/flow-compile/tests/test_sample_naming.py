"""Tests for Flow sample naming rules."""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.sample_naming import (
    build_flow_sample_name,
    infer_replicate_label,
    sanitize_name_token,
    validate_flow_sample_name,
)


class TestReplicateInference:
    def test_iclip_dhx9_titles(self):
        assert infer_replicate_label("iCLIP-DHX9-1") == "Rep1"
        assert infer_replicate_label("iCLIP-DHX9-2") == "Rep2"

    def test_explicit_rep(self):
        assert infer_replicate_label("FLASH-STAU2_rep2") == "Rep2"


class TestSampleNaming:
    def test_no_spaces_in_flow_sample_name(self):
        name = build_flow_sample_name(
            "DHX9",
            "ATCC Cell Lines",
            "Hs",
            "iCLIP-DHX9-2",
            "SRR6181534",
        )
        assert name == "DHX9_Hs_ATCC_Cell_Lines_Rep2_SRR6181534"
        assert validate_flow_sample_name(name) == []

    def test_rep1_for_first_replicate(self):
        name = build_flow_sample_name(
            "DHX9",
            "ATCC Cell Lines",
            "Hs",
            "iCLIP-DHX9-1",
            "SRR6181530",
        )
        assert name == "DHX9_Hs_ATCC_Cell_Lines_Rep1_SRR6181530"

    def test_sanitize_removes_special_chars(self):
        assert sanitize_name_token("ATCC Cell Lines") == "ATCC_Cell_Lines"

    def test_rejects_spaces(self):
        assert "spaces" in validate_flow_sample_name("bad name")[0]
