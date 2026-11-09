"""Resolve the response language for a chat turn and remember explicit choices.

Sole owner of:
  - language detection from input text (via app.language.detect_query_languages)
  - session-language memory read/write (via app.services.lang_memory)

Priority (per the approved design):
  1. explicit request embedded in the user's text (e.g. "explain in Marathi")
  2. explicit UI language selection passed by the frontend
  3. existing session language (remembered from a previous explicit choice)
  4. detected dominant input language (NOT persisted — detection must never
     silently override an explicit choice)
  5. English fallback
"""
from app.language import detect_query_languages, _load_config
from app.services.lang_memory import (
    get_session_language,
    set_session_language,
    DEFAULT_LANGUAGE,
)

_cfg = _load_config()
SUPPORTED_LANGUAGES = set(_cfg.get("supported_languages", ["en", "hi", "gu", "mr", "bn"]))


def _is_supported(lang: str | None) -> bool:
    return isinstance(lang, str) and lang in SUPPORTED_LANGUAGES


def resolve_and_remember(
    session_id: str,
    input_text: str,
    ui_language_explicit: str | None = None,
    user_id: str | None = None,
) -> str:
    """Resolve response language with owner-namespaced memory.

    user_id is the authenticated Clerk sub (None preserves the legacy
    offline/test path). Memory is keyed by (user_id, session_id) so a
    foreign session_id can neither read nor overwrite another owner's
    remembered language.
    """
    detected = detect_query_languages(input_text or "")
    explicit_request = detected.get("explicit_request")

    # 1) explicit request embedded in the query text
    if _is_supported(explicit_request):
        set_session_language(session_id, explicit_request, user_id=user_id)
        return explicit_request

    # 2) explicit UI language selection from the frontend
    if _is_supported(ui_language_explicit):
        set_session_language(session_id, ui_language_explicit, user_id=user_id)
        return ui_language_explicit

    # 3) existing remembered session language
    existing = get_session_language(session_id, user_id=user_id)
    if _is_supported(existing):
        return existing

    # 4) detected dominant input language — used for THIS turn only
    dominant = detected.get("dominant")
    if _is_supported(dominant):
        return dominant

    # 5) English fallback
    return DEFAULT_LANGUAGE
