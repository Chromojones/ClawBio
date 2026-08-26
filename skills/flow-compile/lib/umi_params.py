"""Re-export shim: this module merged into `lib/read_structure.py`.

Kept so existing callers and tests keep working across the merge. Deleted in the final
cleanup commit of the rebuild.
"""

from lib.read_structure import (  # noqa: F401
    Check,
    ERROR,
    INFO,
    WARNING,
    UmiParamCheck,
    check_umi_params,
)
