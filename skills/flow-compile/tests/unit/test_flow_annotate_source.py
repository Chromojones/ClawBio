"""Source (Cell or Tissue) precedence: the real line beats the supplier phrase.

GEO `!Sample_source_name_ch1` is frequently a supplier or descriptive phrase while the
actual line sits in a `cell line:` / `cell type:` characteristic. GSE105082 is the
canonical case: source_name is "ATCC Cell Lines", characteristics say "cell type: HeLa".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.flow_annotate import resolve_source  # noqa: E402


class TestSourcePrecedence:
    def test_cell_type_characteristic_beats_supplier_source_name(self):
        assert (
            resolve_source(
                source_name="ATCC Cell Lines",
                characteristics=["cell type: HeLa", "treatment: none"],
            )
            == "HeLa"
        )

    def test_cell_line_characteristic_beats_generic_descriptor(self):
        """GSE215250: source_name 'human embryonic kidney', characteristic 'cell line: HEK293'."""
        assert (
            resolve_source(
                source_name="human embryonic kidney",
                characteristics=["cell line: HEK293", "genotype: wildtype"],
            )
            == "HEK293"
        )

    def test_source_name_used_when_no_characteristic(self):
        assert resolve_source(source_name="HeLa", characteristics=[]) == "HeLa"

    def test_empty_when_nothing_available(self):
        assert resolve_source(source_name="", characteristics=[]) == ""
