"""Shared fixtures: the demo study's file paths."""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

GSE105082_MATRIX = SKILL_DIR / "demo" / "GSE105082_series_matrix.txt"
GSE105082_SRR_MAP = SKILL_DIR / "demo_gse105082_srr_map.tsv"
GSE105082_PAPER = SKILL_DIR / "demo" / "paper_PMC6307142_iclip_excerpt.txt"
DEMO_DIR = SKILL_DIR / "demo"


@pytest.fixture
def gse105082_matrix():
    return GSE105082_MATRIX


@pytest.fixture
def gse105082_srr_map():
    return GSE105082_SRR_MAP


@pytest.fixture
def demo_dir():
    return DEMO_DIR
