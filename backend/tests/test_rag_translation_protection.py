"""RAG back-translation protection (P0): digit-free placeholders + URL safety.

Sarvam translates with numerals_format=native, which localizes ASCII digits
inside placeholder tokens so they can never be restored. Placeholders must
therefore be alphabetic-only, and raw portal URLs must survive translation.
"""
from unittest.mock import patch

from app.config import Settings
from app.routes import chat as chat_route


def _settings() -> Settings:
    return Settings(
        groq_api_key="test", gemini_api_key="test",
        supabase_url="http://test", supabase_service_key="test",
    )


def test_alpha_index_is_digit_free_and_unique():
    seen = set()
    for i in range(5000):
        token = chat_route._alpha_index(i)
        assert token and all("A" <= c <= "Z" for c in token), token
        assert token not in seen
        seen.add(token)
    assert chat_route._alpha_index(0) == "A"
    assert chat_route._alpha_index(25) == "Z"
    assert chat_route._alpha_index(26) == "AA"


def test_back_translation_restores_citations_and_urls():
    # Test that when Sarvam returns non-English text with protected tokens,
    # the tokens are correctly restored to URLs and citations.
    # Use enough Gujarati text to keep ASCII ratio below 0.55 threshold.
    text = "Visit https://pmfby.gov.in/portal for [chunk:abcdefgh] details."
    with patch.object(chat_route, "SarvamTranslator") as mock_cls:
        inst = mock_cls.return_value
        inst.configured = True
        # The protected text has URLs/citations replaced with tokens.
        # Simulate Sarvam translating to Gujarati while preserving tokens.
        def fake_translate(protected_text, **kw):
            # Extract just the tokens (they survive translation unchanged)
            tokens = [w for w in protected_text.split() if w.startswith("RAGURL") or w.startswith("TRANSLATIONCITATION")]
            # Return lots of Gujarati text with tokens embedded to dilute ASCII ratio
            # ~60 Gujarati letters vs ~32 ASCII letters from tokens = ratio ~0.35 < 0.55
            gujarati = ("જાણો અહીં માહિતી જાણો અહીં માહિતી જાણો અહીં "
                        "માહિતી જાણો અહીં માહિતી જાણો અહીં માહિતી")  # ~60 chars
            return gujarati + " " + " ".join(tokens)
        inst.translate.side_effect = fake_translate
        out = chat_route._translate_from_english(text, "gu", _settings())
    # The result should have tokens restored to original URLs/citations
    assert "https://pmfby.gov.in/portal" in out, f"URL not restored: {out}"
    assert "[chunk:abcdefgh]" in out, f"Citation not restored: {out}"
    # No raw tokens should remain
    assert "RAGURL" not in out
    assert "TRANSLATIONCITATION" not in out
    # Should contain Gujarati (translation happened)
    assert "જાણો" in out


def test_back_translation_falls_back_to_original_without_leak():
    text = "See https://example.gov.in/x [chunk:abcdefgh] for help."
    with patch.object(chat_route, "SarvamTranslator") as mock_cls:
        mock_cls.return_value.configured = False
        with patch.object(chat_route, "AzureTranslator") as azure_cls:
            azure_cls.return_value.translate.side_effect = RuntimeError("down")
            out = chat_route._translate_from_english(text, "gu", _settings())
    assert out == text
    assert "TRANSLATIONCITATION" not in out
    assert "RAGURL" not in out
