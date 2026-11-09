import pytest
from app.resolve_response_language import resolve_and_remember
from app.services.lang_memory import (
    get_session_language,
    set_session_language,
    clear_session_language,
)

_SESS = "t4-sess"


@pytest.fixture(autouse=True)
def _clean():
    clear_session_language(_SESS)
    yield
    clear_session_language(_SESS)


def test_explicit_request_in_text_persists():
    out = resolve_and_remember(_SESS, "PMFBY म्हणजे काय? explain in Marathi")
    assert out == "mr"
    assert get_session_language(_SESS) == "mr"


def test_ui_language_explicit_persists():
    out = resolve_and_remember(_SESS, "what is PMFBY", ui_language_explicit="hi")
    assert out == "hi"
    assert get_session_language(_SESS) == "hi"


def test_existing_session_wins_over_detection():
    set_session_language(_SESS, "hi")
    # English input must NOT switch an explicit Hindi session to English
    out = resolve_and_remember(_SESS, "what is the premium amount")
    assert out == "hi"


def test_detected_dominant_not_persisted():
    # Input is Indic-dominant (no Latin acronym) so detection yields hi/mr.
    # NOTE: "PMFBY क्या है" returns dominant="en" under the real detector
    # (Latin acronym + 0.7 script_threshold), so it cannot exercise path #4.
    out = resolve_and_remember(_SESS, "योजना के बारे में जानकारी दें")
    assert out in ("hi", "mr")
    # detection must NOT write session memory
    assert get_session_language(_SESS) is None


def test_fallback_to_en():
    out = resolve_and_remember(_SESS, "what is the weather like today")
    assert out == "en"


def test_explicit_request_beats_ui_selection():
    out = resolve_and_remember(_SESS, "explain in Gujarati please", ui_language_explicit="hi")
    assert out == "gu"
