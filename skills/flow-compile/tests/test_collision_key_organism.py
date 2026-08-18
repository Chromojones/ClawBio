"""The replicate-collision key must include the biological source.

GSE58448 is coilin-GFP iCLIP in two species: 5 replicates in mouse P19 and 2 in human HeLa.
Mouse replicate 1 and human replicate 1 share target `COIL`, tag `cGFP` and condition
`BAC transgene, endogenous-level expression`, so the check fired:

    2 samples share target COIL and replicate 1 ... a distinction was lost

No distinction was lost. They are different organisms in different cell lines — the key
simply could not see it.

This is the second false positive of the same shape. E-MTAB-2700 fired on `nT7` vs `nGFP`
arms until the tag joined the key. Both times the tempting fix was to push the distinguishing
value into `Condition` to quiet the check, which would corrupt the metadata to satisfy a
guardrail. The right fix is the key.

`Cell or Tissue` and `Organism` both go in: a study can legitimately run the same protein in
two cell lines of one species (and GSE76475 already relies on `Condition` separating
fractions within one line).
"""

import sys
from pathlib import Path

import pandas as pd

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.metadata_validate import find_replicate_collisions  # noqa: E402


def row(**kw):
    base = {
        "Sample Name": "X_rep1", "Protein (Purification Target)": "COIL",
        "Purification Target Annotation": "cGFP", "Purification Agent": "Goat Anti-GFP",
        "Cell or Tissue": "P19", "Organism": "Mm",
        "Condition": "BAC transgene, endogenous-level expression",
    }
    base.update(kw)
    return base


class TestTheGse58448FalsePositive:
    def test_two_species_same_replicate_is_not_a_collision(self):
        table = pd.DataFrame([
            row(**{"Sample Name": "COIL_P19_Mm_cGFP_rep1", "Cell or Tissue": "P19", "Organism": "Mm"}),
            row(**{"Sample Name": "COIL_HeLa_Hs_cGFP_rep1", "Cell or Tissue": "HeLa", "Organism": "Hs"}),
        ])
        assert find_replicate_collisions(table) == []

    def test_two_cell_lines_in_one_species_is_not_a_collision(self):
        table = pd.DataFrame([
            row(**{"Sample Name": "COIL_P19_Mm_cGFP_rep1", "Cell or Tissue": "P19"}),
            row(**{"Sample Name": "COIL_N2A_Mm_cGFP_rep1", "Cell or Tissue": "N2A"}),
        ])
        assert find_replicate_collisions(table) == []


class TestItStillCatchesTheRealThing:
    def test_a_genuine_duplicate_still_fires(self):
        """Same everything — the GSE290281 mislabelled-input shape."""
        table = pd.DataFrame([
            row(**{"Sample Name": "RNPS1_IP_rep1"}),
            row(**{"Sample Name": "RNPS1_INPUT_rep1"}),
        ])
        assert len(find_replicate_collisions(table)) == 1

    def test_same_source_different_condition_is_still_allowed(self):
        """GSE76475: RBFOX1 rep1 in HMW and soluble fractions."""
        table = pd.DataFrame([
            row(**{"Sample Name": "RBFOX1_hmw_rep1", "Condition": "HMW"}),
            row(**{"Sample Name": "RBFOX1_sol_rep1", "Condition": "soluble"}),
        ])
        assert find_replicate_collisions(table) == []

    def test_same_source_different_tag_is_still_allowed(self):
        """E-MTAB-2700: nT7 vs nGFP arms."""
        table = pd.DataFrame([
            row(**{"Sample Name": "A3G_T7_rep1", "Purification Target Annotation": "nT7"}),
            row(**{"Sample Name": "A3G_GFP_rep1", "Purification Target Annotation": "nGFP"}),
        ])
        assert find_replicate_collisions(table) == []


class TestMissingColumns:
    def test_a_sheet_without_source_columns_still_works(self):
        """Edit sheets omit them; the check must degrade, not crash."""
        table = pd.DataFrame([
            {"Sample Name": "RNPS1_IP_rep1", "Protein (Purification Target)": "RNPS1",
             "Purification Target Annotation": "", "Condition": "x"},
            {"Sample Name": "RNPS1_INPUT_rep1", "Protein (Purification Target)": "RNPS1",
             "Purification Target Annotation": "", "Condition": "x"},
        ])
        assert len(find_replicate_collisions(table)) == 1
