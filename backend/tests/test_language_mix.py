"""Tests for mixed language detection."""
from app.language import detect_query_languages


def test_english_only():
    result = detect_query_languages("What is the premium rate?")
    assert result["dominant"] == "en"
    assert result["language_mix"] is None


def test_hindi_only():
    result = detect_query_languages("पीएमएफबीवाई योजना क्या है?")
    assert result["dominant"] == "hi"
    assert result["language_mix"] is None


def test_hindi_english_script_mix_detected():
    """Script-detectable mix: Devanagari + Latin."""
    result = detect_query_languages("PMFBY योजना kya hai")
    assert result["dominant"] in ("hi", "en")
    assert result["language_mix"] is not None
    assert "hi" in result["language_mix"] or "en" in result["language_mix"]


def test_pure_latin_not_detected_as_mix():
    """Romanized Hindi/Gujarati in Latin script — script analysis can't detect mix.
    Sarvam-105B handles this natively through the prompt instruction."""
    result = detect_query_languages("PMFBY scheme kya hai")
    assert result["language_mix"] is None


def test_gujarati_only():
    result = detect_query_languages("ગુજરાત સહકાર યોજના")
    assert result["dominant"] == "gu"
    assert result["language_mix"] is None


def test_mixed_returns_dict():
    result = detect_query_languages("Cooperative society ka rules")
    assert isinstance(result, dict)
    assert "languages" in result
    assert "dominant" in result
    assert "language_mix" in result
