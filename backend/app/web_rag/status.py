"""P1-8 status-evidence branch: retrieve authoritative current-status.

Fires for questions where actual status matters (active, discontinued,
superseded, amended, open/closed, current season/year, current route).
Detection: STATUS intent OR explicit status vocabulary (English plus
the repository-verified Gujarati/Hindi status words only).

The branch targets status-bearing publishers (subject anchors plus
PIB and Digital Sansad for dated status evidence) through the same
official-only + allow mechanism. It does NOT infer status: currency
comes from P0 validity metadata, and uncertainty stays explicit
(unknown validity is never presented as current).
"""

from __future__ import annotations

import re

# Verified vocabulary: INTENT_KEYWORDS status words + plain English.
# No invented translations.
STATUS_WORDS = [
    "status",
    "active",
    "discontinued",
    "still running",
    "is it working",
    "in force",
    "currently",
    "latest update",
    "as on",
    "open now",
    "presently",
    "સ્થિતિ",
    "स्थिति",
]

_STATUS_RES = [
    re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    if word.isascii()
    else re.compile(re.escape(word))
    for word in STATUS_WORDS
]

# Status-bearing publishers appended to subject anchors (all verified).
STATUS_PUBLISHERS = ["pib.gov.in", "sansad.in"]

STATUS_QUERY_TERMS = ["status", "latest update", "as on"]


def is_status_query(query: str, intent: str | None = None) -> bool:
    """True when the question asks about current status."""
    if (intent or "").upper() == "STATUS":
        return True
    text = str(query or "")
    return any(rx.search(text) for rx in _STATUS_RES)


def status_branch_terms() -> list[str]:
    """Bounded augmenting terms for the status branch."""
    return list(STATUS_QUERY_TERMS)
