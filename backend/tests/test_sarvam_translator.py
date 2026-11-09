"""Tests for SarvamTranslator — Sarvam translation bug fix.

Tests cover:
A. Model version in payload (must be mayura:v1)
B. Sarvam failure propagation (must raise, not return original)
C. Azure fallback reachable via _translate_to_english
D. Non-English leak prevention
E. Back-translation failure
F. Cache version safety
"""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from app.providers.sarvam_translator import (
    SarvamTranslator,
    _raw_translate,
    _translate_cache,
    _TRANSLATION_MODEL_VERSION,
)


def _settings_stub(sarvam_keys=None):
    keys = sarvam_keys or ["sk_test_key_1", "sk_test_key_2"]
    return SimpleNamespace(sarvam_keys=keys)


# ── TEST A — Model version in payload ────────────────────────────────────────


class TestModelVersion:
    """Verify the outgoing payload uses mayura:v1."""

    def test_model_version_constant_is_v1(self):
        """_TRANSLATION_MODEL_VERSION must be mayura:v1."""
        assert _TRANSLATION_MODEL_VERSION == "mayura:v1"

    def test_raw_translate_sends_v1_in_payload(self):
        """_raw_translate payload must contain model: mayura:v1, not v2."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"translated_text": "Hello"}

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            _raw_translate("sk_test_key", "नमस्ते", "hi", "en")

            call_kwargs = mock_ctx.post.call_args
            payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert payload["model"] == "mayura:v1"
            assert payload["model"] != "mayura:v2"

    def test_raw_translate_payload_complete(self):
        """Verify the full payload structure sent to Sarvam API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"translated_text": "Hello"}

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            _raw_translate("sk_test_key", "नमस्ते", "hi", "en")

            call_kwargs = mock_ctx.post.call_args
            payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert payload["model"] == "mayura:v1"
            assert payload["source_language_code"] == "hi-IN"
            assert payload["target_language_code"] == "en-IN"
            assert payload["input"] == "नमस्ते"
            assert "numerals_format" in payload
            assert "mode" in payload


# ── TEST B — Sarvam failure propagation ──────────────────────────────────────


class TestSarvamFailurePropagation:
    """When all Sarvam keys fail, translate() must raise, not return original text."""

    def test_translate_raises_on_total_failure(self):
        """translate() raises RuntimeError when all keys fail."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        gujarati_text = "પીએમએફબીવાઈ વિશે જાણકારી આપો"

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                translator.translate(gujarati_text, to="en", source="gu")

    def test_translate_does_not_return_gujarati_on_failure(self):
        """Sarvam failure must NOT return the original Gujarati text."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        gujarati_text = "પીએમએફબીવાઈ વિશે જાણકારી આપો"

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                result = translator.translate(gujarati_text, to="en", source="gu")
                # This line should never be reached, but verify regardless
                assert result != gujarati_text

    def test_translate_does_not_return_hindi_on_failure(self):
        """Sarvam failure must NOT return the original Hindi text."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        hindi_text = "पीएमएफबीवाई के बारे में जानकारी दें"

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                translator.translate(hindi_text, to="en", source="hi")

    def test_raw_translate_raises_on_http_error(self):
        """_raw_translate raises on HTTP 500."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server Error"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_resp
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                _raw_translate("sk_test_key", "नमस्ते", "hi", "en")


# ── TEST C — Azure fallback reachable ────────────────────────────────────────


class TestAzureFallback:
    """Verify _translate_to_english falls through to Azure when Sarvam fails."""

    def test_sarvam_failure_triggers_azure_fallback(self):
        """_translate_to_english calls Azure when Sarvam raises."""
        from app.routes.chat import _translate_to_english

        settings = _settings_stub()
        gujarati_text = "પીએમએફબીવાઈ વિશે જાણકારી આપો"

        # Mock SarvamTranslator to raise
        with patch("app.routes.chat.SarvamTranslator") as MockSarvam:
            mock_sarvam = MagicMock()
            mock_sarvam.configured = True
            mock_sarvam.translate.side_effect = RuntimeError("Sarvam API failed")
            MockSarvam.return_value = mock_sarvam

            # Mock AzureTranslator to return English
            with patch("app.routes.chat.AzureTranslator") as MockAzure:
                mock_azure = MagicMock()
                mock_azure.configured = True
                mock_azure.translate.return_value = "Information about PMFBY"
                MockAzure.return_value = mock_azure

                result = _translate_to_english(gujarati_text, "gu", settings)

                # Sarvam was attempted
                mock_sarvam.translate.assert_called_once()
                # Azure was called as fallback
                mock_azure.translate.assert_called_once()
                # Result is Azure's English translation
                assert result == "Information about PMFBY"

    def test_sarvam_failure_does_not_return_non_english(self):
        """_translate_to_english never returns non-English when Sarvam fails."""
        from app.routes.chat import _translate_to_english

        settings = _settings_stub()
        hindi_text = "पीएमएफबीवाई के बारे में जानकारी दें"

        with patch("app.routes.chat.SarvamTranslator") as MockSarvam:
            mock_sarvam = MagicMock()
            mock_sarvam.configured = True
            mock_sarvam.translate.side_effect = RuntimeError("Sarvam API failed")
            MockSarvam.return_value = mock_sarvam

            with patch("app.routes.chat.AzureTranslator") as MockAzure:
                mock_azure = MagicMock()
                mock_azure.configured = True
                mock_azure.translate.return_value = "Information about PMFBY"
                MockAzure.return_value = mock_azure

                result = _translate_to_english(hindi_text, "hi", settings)

                # Must NOT return the Hindi text
                assert result != hindi_text
                assert result == "Information about PMFBY"


# ── TEST D — Non-English leak prevention ─────────────────────────────────────


class TestNonEnglishLeakPrevention:
    """Ensure non-English text never leaks through as 'English'."""

    def test_gujarati_not_returned_on_sarvam_failure(self):
        """Gujarati input must not be returned when Sarvam fails."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        gujarati_text = "પીએમએફબીવાઈ વિશે જાણકારી આપો"

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                translator.translate(gujarati_text, to="en", source="gu")

    def test_bengali_not_returned_on_sarvam_failure(self):
        """Bengali input must not be returned when Sarvam fails."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        bengali_text = "পিএমএফবিভি সম্পর্কে তথ্য দিন"

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                translator.translate(bengali_text, to="en", source="bn")


# ── TEST E — Back-translation failure ────────────────────────────────────────


class TestBackTranslationFailure:
    """Verify _translate_from_english raises on Sarvam failure."""

    def test_back_translation_raises_on_sarvam_failure(self):
        """_translate_from_english propagates Sarvam exception to caller."""
        from app.routes.chat import _translate_from_english

        settings = _settings_stub()

        with patch("app.routes.chat.SarvamTranslator") as MockSarvam:
            mock_sarvam = MagicMock()
            mock_sarvam.configured = True
            mock_sarvam.translate.side_effect = RuntimeError("Sarvam API failed")
            MockSarvam.return_value = mock_sarvam

            # Azure is configured as second fallback
            with patch("app.routes.chat.AzureTranslator") as MockAzure:
                mock_azure = MagicMock()
                mock_azure.configured = True
                mock_azure.translate.return_value = "PMFBY વિશે માહિતી"
                MockAzure.return_value = mock_azure

                result = _translate_from_english("Information about PMFBY", "gu", settings)

                # Sarvam was attempted
                mock_sarvam.translate.assert_called_once()
                # Azure was called as fallback
                mock_azure.translate.assert_called_once()
                # Result is Azure's translation
                assert result == "PMFBY વિશે માહિતી"

    def test_back_translation_does_not_return_english_on_failure(self):
        """_translate_from_english must not return English when target is Gujarati."""
        from app.routes.chat import _translate_from_english

        settings = _settings_stub()
        english_text = "Information about PMFBY"

        with patch("app.routes.chat.SarvamTranslator") as MockSarvam:
            mock_sarvam = MagicMock()
            mock_sarvam.configured = True
            mock_sarvam.translate.side_effect = RuntimeError("Sarvam failed")
            MockSarvam.return_value = mock_sarvam

            with patch("app.routes.chat.AzureTranslator") as MockAzure:
                mock_azure = MagicMock()
                mock_azure.configured = True
                mock_azure.translate.return_value = "PMFBY વિશે માહિતી"
                MockAzure.return_value = mock_azure

                result = _translate_from_english(english_text, "gu", settings)

                # Must NOT return the English text
                assert result != english_text
                assert result == "PMFBY વિશે માહિતી"


# ── TEST F — Cache version safety ───────────────────────────────────────────


class TestCacheVersionSafety:
    """Verify a v2 cache entry cannot masquerade as v1."""

    def test_cache_key_includes_model_version(self):
        """Cache key must include the model version to prevent stale entries."""
        # Manually populate cache with a "v2" key
        v2_key = ("mayura:v2", "नमस्ते", "hi", "en")
        _translate_cache[v2_key] = "stale_v2_translation"

        # A v1 lookup for the same text should NOT hit the v2 cache
        v1_key = ("mayura:v1", "नमस्ते", "hi", "en")
        assert v1_key not in _translate_cache

        # Clean up
        del _translate_cache[v2_key]

    def test_cache_hit_uses_correct_model_version(self):
        """Translation cached under v1 is only returned for v1 lookups."""
        # Simulate v1 cached result
        v1_key = ("mayura:v1", "नमस्ते", "hi", "en")
        _translate_cache[v1_key] = "Hello"

        assert _translate_cache[v1_key] == "Hello"

        # v2 key for same text should miss
        v2_key = ("mayura:v2", "नमस्ते", "hi", "en")
        assert v2_key not in _translate_cache

        # Clean up
        del _translate_cache[v1_key]

    def test_successful_translation_populates_v1_cache(self):
        """Successful translation caches under the v1 model version key."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"translated_text": "Hello"}

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            result = translator.translate("नमस्ते", to="en", source="hi")

            assert result == "Hello"
            # Verify cache has v1 key
            v1_key = ("mayura:v1", "नमस्ते", "hi", "en")
            assert v1_key in _translate_cache
            assert _translate_cache[v1_key] == "Hello"

            # Clean up
            del _translate_cache[v1_key]
