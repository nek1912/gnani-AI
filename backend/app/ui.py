"""UI strings — loaded from data/ui_strings.json.

No hardcoded user-facing text in route handlers.
"""
import json
from functools import lru_cache
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"


@lru_cache(maxsize=1)
def _load_ui_strings() -> dict:
    """Load UI strings from JSON config (cached)."""
    path = DATA_DIR / "ui_strings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def get_abstain_text(language: str) -> str:
    """Get the abstention message for the given language."""
    strings = _load_ui_strings()
    abstain = strings.get("abstain_text", {})
    return abstain.get(language, abstain.get("en", "No answer found."))
