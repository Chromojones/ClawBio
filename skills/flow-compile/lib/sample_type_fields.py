"""Re-export shim: this module merged into `lib/import_guards.py`.

Kept so existing callers and tests keep working across the merge. Deleted in the final
cleanup commit of the rebuild.
"""

from lib.import_guards import (  # noqa: F401
    Check,
    ERROR,
    INFO,
    WARNING,
    REJECTED_BY_SAMPLE_TYPE,
    check_upload_fields,
    strip_rejected,
)
