"""Re-export shim: this module merged into `lib/read_structure.py`.

Kept so existing callers and tests keep working across the merge. Deleted in the final
cleanup commit of the rebuild.
"""

from lib.read_structure import (  # noqa: F401
    Check,
    ERROR,
    INFO,
    WARNING,
    InlineLayout,
    infer_inline_layout,
    FIXED_MIN_DEV,
    UNIFORM_MAX_DEV,
    GENOMIC_MIN_DEV,
)
