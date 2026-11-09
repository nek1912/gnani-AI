import pytest
from app.services.lang_memory import (
    get_session_language,
    set_session_language,
    clear_session_language,
    DEFAULT_LANGUAGE,
)


def test_unset_session_returns_none():
    assert get_session_language("sess-unset") is None


def test_default_language_constant_is_english():
    assert DEFAULT_LANGUAGE == "en"


def test_set_then_get():
    set_session_language("sess-1", "hi")
    assert get_session_language("sess-1") == "hi"


def test_clear():
    set_session_language("sess-2", "bn")
    clear_session_language("sess-2")
    assert get_session_language("sess-2") is None


def test_empty_session_id_rejected():
    with pytest.raises(ValueError):
        set_session_language("", "hi")


def test_empty_language_rejected():
    with pytest.raises(ValueError):
        set_session_language("sess-3", "")
