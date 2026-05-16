"""
Marker extraction — the "enrichment" in Automated Enrichment Pipeline.

Pulls structured facts out of raw text:
- dates
- metrics (numbers with units)
- error codes

These markers are stored alongside chunks so downstream queries can
filter by marker type — e.g. "show all chunks mentioning ERROR-502".
"""

import re
from typing import Any


DATE_RE = re.compile(
    r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
    r'|\d{4}-\d{2}-\d{2}'
    r'|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b',
    re.IGNORECASE,
)

METRIC_RE = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds?|%|MB|GB|TB|KB|USD|\$|req/s|rpm|RPS|vCPU|GiB|MiB)\b',
    re.IGNORECASE,
)

ERROR_RE = re.compile(
    r'\b(?:ERR(?:OR)?[-_]?\d+|[45]\d{2}\s+(?:error|timeout|unavailable)|exception|traceback|fatal)\b',
    re.IGNORECASE,
)


def extract_markers(text: str) -> dict[str, list[str]]:
    """Return a dict of marker lists found in text."""
    return {
        "dates": list(dict.fromkeys(DATE_RE.findall(text))),
        "metrics": list(dict.fromkeys(METRIC_RE.findall(text))),
        "error_codes": list(dict.fromkeys(ERROR_RE.findall(text))),
    }
