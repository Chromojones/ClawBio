"""Re-export shim: this module merged into `lib/study_check.py`.

Kept so existing callers and tests keep working across the merge. Deleted in the final
cleanup commit of the rebuild.
"""

from lib.study_check import (  # noqa: F401
    Check,
    ERROR,
    INFO,
    WARNING,
    Availability,
    parse_geo_response,
    geo_url,
)
