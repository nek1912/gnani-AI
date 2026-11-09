import pytest

from app.language import normalize_language


def test_selection_wins_on_plain_english():
    assert normalize_language("en", "What is PMFBY eligibility?") == "en"


def test_devanagari_overrides_en_selection():
    assert normalize_language("en", "पीएमएफबीवाई में कैसे आवेदन करें") == "hi"


def test_latin_script_hindi_stays_hi():
    # Latin-script Hindi must NOT flip just because of script
    assert normalize_language("hi", "meri fasal ka insurance kaise milega") == "hi"


def test_invalid_selection_rejected():
    with pytest.raises(ValueError):
        normalize_language("fr", "bonjour")


from app.language import detect_query_languages, english_retrieval_query
from app.config import get_settings


def test_detect_mixed_hindi_english():
    d = detect_query_languages("PMFBY क्या है and premium कितना है?")
    assert "hi" in d["languages"] and "en" in d["languages"]
    assert d["dominant"] is not None


def test_detect_explicit_request_marathi():
    d = detect_query_languages("PMFBY म्हणजे काय? explain in Marathi")
    assert d["explicit_request"] == "mr"


def test_detect_explicit_request_gujarati_native():
    d = detect_query_languages("આ વિશે ગુજરાતી માં સમજાવો")
    assert d["explicit_request"] == "gu"


def test_detect_marathi_not_hindi():
    d = detect_query_languages("मला मराठीत उत्तर हवे आहे")
    assert "mr" in d["languages"]
    assert d["dominant"] in ("mr", "hi")


def test_english_retrieval_preserves_latin_entities(monkeypatch):
    settings = get_settings()

    class _FakeT:
        def translate(self, t, to, source):
            # only Indic runs reach here; Latin runs are never passed to translate
            return t.replace("શું", "WHAT").replace("કેટલું", "HOWMUCH")

    monkeypatch.setattr("app.providers.translator.AzureTranslator", lambda s: _FakeT())
    out = english_retrieval_query("PMFBY શું કેટલું and farmer premium 500", None, settings)
    assert "PMFBY" in out and "farmer" in out and "premium" in out and "500" in out
    assert "WHAT" in out and "HOWMUCH" in out  # Indic runs were translated
