"""Re-export shim: this module merged into `lib/import_check.py`.

Kept so existing callers and tests keep working across the merge. Deleted in the final
cleanup commit of the rebuild.
"""

from lib.import_check import (  # noqa: F401
    find_already_present,
    names_from_listing,
)
