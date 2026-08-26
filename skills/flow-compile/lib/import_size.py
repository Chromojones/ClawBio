"""Re-export shim: this module merged into `lib/import_guards.py`.

Kept so existing callers and tests keep working across the merge. Deleted in the final
cleanup commit of the rebuild.
"""

from lib.import_guards import (  # noqa: F401
    Check,
    ERROR,
    INFO,
    WARNING,
    LARGEST_KNOWN_GOOD_BYTES,
    KNOWN_FAILURE_BYTES,
    DEFAULT_BATCH_BYTES,
    total_bytes,
    check_import_size,
    split_into_batches,
)
