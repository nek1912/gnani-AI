"""Lightweight, script-based mixed-language detection.

Used only to decide whether to show a "you used multiple languages"
notice on the final grievance draft. This is a presentation-only
heuristic and does not feed into, or alter, translation, retrieval,
or answer generation anywhere else in the system.
"""

from __future__ import annotations

import re

# Unicode block ranges for the scripts this product supports.
_SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "latin": ((0x0041, 0x005A), (0x0061, 0x007A)),
    "devanagari": ((0x0900, 0x097F),),  # Hindi, Marathi
    "bengali": ((0x0980, 0x09FF),),
    "gujarati": ((0x0A80, 0x0AFF),),
    "tamil": ((0x0B80, 0x0BFF),),
}

# Minimum number of letters from a script before it counts as
# "present" — avoids flagging a single stray character (e.g. a name)
# as a full second language.
_MIN_LETTERS = 3


def detect_mixed_language(*texts: str | None) -> bool:
    """Return True if the combined text contains letters from more
    than one supported script in meaningful quantity."""
    combined = " ".join(t for t in texts if t)
    if not combined:
        return False

    counts: dict[str, int] = {script: 0 for script in _SCRIPT_RANGES}
    for ch in combined:
        cp = ord(ch)
        if not re.match(r"\w", ch, re.UNICODE):
            continue
        for script, ranges in _SCRIPT_RANGES.items():
            if any(lo <= cp <= hi for lo, hi in ranges):
                counts[script] += 1
                break

    scripts_present = [s for s, c in counts.items() if c >= _MIN_LETTERS]
    return len(scripts_present) > 1
