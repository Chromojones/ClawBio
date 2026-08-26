"""Re-export shim: this module merged into `lib/import_check.py`.

Kept so existing callers and tests keep working across the merge. Deleted in the final
cleanup commit of the rebuild.
"""

from lib.import_check import (  # noqa: F401
    Discrepancy,
    count_reads,
    find_import_discrepancies,
    format_report,
    live_metadata,
    project_id_of,
    NON_METADATA_COLUMNS,
    ANNOTATION_SUFFIX,
)
