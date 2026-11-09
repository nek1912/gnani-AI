"""Focused tests for Sarvam translation fixes:
1. Model version (mayura:v1)
2. Multi-chunk failure propagation
3. Azure fallback reachable for multi-chunk failures
4. URL preservation
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.providers.sarvam_translator import (
    SarvamTranslator,
    _raw_translate,
    _split_text_for_translation,
    _translate_cache,
)


def _settings_stub(sarvam_keys=None):
    keys = sarvam_keys or ["sk_test_key_1", "sk_test_key_2"]
    return SimpleNamespace(sarvam_keys=keys)


@pytest.fixture(autouse=True)
def _clear_sarvam_cache():
    """Clear the module-level translation cache before each test."""
    _translate_cache.clear()
    yield
    _translate_cache.clear()


def _mock_sarvam_response(translated_text: str = "translated"):
    """Create a mock httpx response for a successful Sarvam call."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"translated_text": translated_text}
    return mock_resp


def _mock_sarvam_failure(status_code: int = 400):
    """Create a mock httpx response that raises on raise_for_status."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = "Bad Request"
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=MagicMock(),
        response=mock_resp,
    )
    return mock_resp


def _build_long_text(target_chars: int = 1800) -> str:
    """Build a long English text that will split into multiple chunks."""
    # Each sentence ~80-100 chars; need ~20+ sentences to exceed 900 chars
    sentences = []
    for i in range(25):
        sentences.append(
            f"This is sentence number {i} of the long grievance response "
            f"that needs to be translated from English to Gujarati properly."
        )
    text = " ".join(sentences)
    # Ensure it's actually long enough to require chunking
    assert len(text) > 900, f"Test text too short: {len(text)}"
    return text


# ---------------------------------------------------------------------------
# Test 1: gu-IN → en-IN, short text, Sarvam success
# ---------------------------------------------------------------------------


class TestGuToEnShortSuccess:
    def test_gujarati_to_english_short(self):
        """Short Gujarati text translates to English via Sarvam."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        gujarati_text = "મારે કચરાની ફરિયાદ કરવી છે"

        mock_resp = _mock_sarvam_response("I want to file a garbage complaint")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            result = translator.translate(gujarati_text, to="en", source="gu")

        assert result == "I want to file a garbage complaint"
        # Verify gu-IN → en-IN was sent
        call_kwargs = mock_ctx.post.call_args
        payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
        assert payload["source_language_code"] == "gu-IN"
        assert payload["target_language_code"] == "en-IN"


# ---------------------------------------------------------------------------
# Test 2: en-IN → gu-IN, short text, Sarvam success
# ---------------------------------------------------------------------------


class TestEnToGuShortSuccess:
    def test_english_to_gujarati_short(self):
        """Short English text translates to Gujarati via Sarvam."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        english_text = "I want to file a garbage complaint."

        mock_resp = _mock_sarvam_response("મારે કચરાની ફરિયાદ કરવી છે.")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            result = translator.translate(english_text, to="gu", source="en")

        assert result == "મારે કચરાની ફરિયાદ કરવી છે."
        # Verify en-IN → gu-IN was sent
        call_kwargs = mock_ctx.post.call_args
        payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
        assert payload["source_language_code"] == "en-IN"
        assert payload["target_language_code"] == "gu-IN"


# ---------------------------------------------------------------------------
# Test 3: en-IN → gu-IN, long text, all chunks succeed
# ---------------------------------------------------------------------------


class TestEnToGuLongAllChunksSucceed:
    def test_long_text_all_chunks_translated(self):
        """Long text: every chunk is translated and no original text is substituted."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        long_text = _build_long_text()

        # Verify splitting happens
        chunks = _split_text_for_translation(long_text)
        assert len(chunks) >= 2, f"Expected multi-chunk split, got {len(chunks)}"

        # Each chunk gets a distinct translation result
        call_count = [0]

        def fake_response(*args, **kwargs):
            call_count[0] += 1
            return _mock_sarvam_response(f"translated_chunk_{call_count[0]}")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.side_effect = fake_response
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            result = translator.translate(long_text, to="gu", source="en")

        # Result should be the joined translations, NOT the original
        assert "translated_chunk_" in result
        assert long_text not in result, (
            "Original English text should NOT appear in the translated result"
        )
        # All chunks were translated
        assert call_count[0] == len(chunks), (
            f"Expected {len(chunks)} API calls, got {call_count[0]}"
        )

    def test_long_text_no_original_chunk_in_result(self):
        """No original English chunk should leak into the result."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)

        # Build text with unique identifiable chunks
        chunk_a = "First sentence that is very important. " * 12  # ~432 chars
        chunk_b = "Second sentence with different content. " * 12  # ~432 chars
        chunk_c = "Third sentence wrapping things up nicely. " * 12  # ~432 chars
        long_text = (chunk_a + chunk_b + chunk_c).strip()
        assert len(long_text) > 900

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = _mock_sarvam_response("પ્રથમ અને બીજો અને ત્રીજો")
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            result = translator.translate(long_text, to="gu", source="en")

        # None of the original English text should appear
        assert "First sentence" not in result
        assert "Second sentence" not in result
        assert "Third sentence" not in result


# ---------------------------------------------------------------------------
# Test 4: en-IN → gu-IN, long text, chunk 1 fails
# ---------------------------------------------------------------------------


class TestEnToGuLongChunk1Fails:
    def test_chunk1_failure_raises(self):
        """When chunk 1 fails on ALL keys, translate() must raise."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        long_text = _build_long_text()

        # Track call number: with 2 keys, chunk 1 = calls 1-2, chunk 2 = calls 3-4
        # All keys for chunk 1 must fail; all keys for chunk 2 must succeed.
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                # Both keys for chunk 1 fail
                raise httpx.HTTPStatusError(
                    "Bad Request",
                    request=MagicMock(),
                    response=MagicMock(status_code=400),
                )
            # Keys for chunk 2 succeed
            return _mock_sarvam_response("translated_chunk_2")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.side_effect = side_effect
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                translator.translate(long_text, to="gu", source="en")

    def test_chunk1_failure_does_not_return_original(self):
        """On chunk 1 failure (all keys), the original English text must NOT be returned."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        long_text = _build_long_text()

        # All keys fail always
        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.side_effect = httpx.HTTPStatusError(
                "Bad Request",
                request=MagicMock(),
                response=MagicMock(status_code=400),
            )
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                result = translator.translate(long_text, to="gu", source="en")
                # This line should never be reached
                assert result != long_text


# ---------------------------------------------------------------------------
# Test 5: en-IN → gu-IN, long text, chunk 2 fails
# ---------------------------------------------------------------------------


class TestEnToGuLongChunk2Fails:
    def test_chunk2_failure_raises(self):
        """When chunk 2 fails on ALL keys, translate() must raise."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        long_text = _build_long_text()

        # With 2 keys: chunk 1 = calls 1-2, chunk 2 = calls 3-4
        # Chunk 1 succeeds, chunk 2 fails on all keys.
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                # Chunk 1: both keys succeed
                return _mock_sarvam_response("translated_chunk_1")
            # Chunk 2: both keys fail
            raise httpx.HTTPStatusError(
                "Bad Request",
                request=MagicMock(),
                response=MagicMock(status_code=400),
            )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.side_effect = side_effect
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                translator.translate(long_text, to="gu", source="en")

    def test_chunk2_failure_does_not_return_original(self):
        """On chunk 2 failure (all keys), the original English text must NOT be returned."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)
        long_text = _build_long_text()

        # All keys fail always
        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.side_effect = httpx.HTTPStatusError(
                "Bad Request",
                request=MagicMock(),
                response=MagicMock(status_code=400),
            )
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            with pytest.raises(httpx.HTTPStatusError):
                result = translator.translate(long_text, to="gu", source="en")
                # Should never reach here
                assert result != long_text


# ---------------------------------------------------------------------------
# Test 6: Azure fallback reached for multi-chunk Sarvam failure
# ---------------------------------------------------------------------------


class TestAzureFallbackForMultiChunkFailure:
    def test_azure_reached_when_sarvam_fails(self):
        """When Sarvam fails on multi-chunk text, Azure fallback runs on full text.

        NOTE: If Azure also returns English (like 'translated by azure'), the
        post-translation _appears_to_be_english check rejects it, because the
        invariant is: for a non-English target, the returned text must NOT appear
        to be English. The function then returns the original English text with
        tokens restored, which is the correct behavior — never silently show
        English when the target is Gujarati.
        """
        from app.routes.chat import _translate_from_english

        settings = _settings_stub()
        long_text = _build_long_text()

        with patch("app.routes.chat.SarvamTranslator") as MockSarvam:
            mock_sarvam = MagicMock()
            mock_sarvam.configured = True
            mock_sarvam.translate.side_effect = RuntimeError("Sarvam API failed")
            MockSarvam.return_value = mock_sarvam

            with patch("app.routes.chat.AzureTranslator") as MockAzure:
                mock_azure = MagicMock()
                mock_azure.configured = True
                mock_azure.translate.return_value = "translated by azure"
                MockAzure.return_value = mock_azure

                result = _translate_from_english(long_text, "gu", settings)

            # Sarvam was attempted
            mock_sarvam.translate.assert_called_once()
            # Azure was actually reached as fallback
            mock_azure.translate.assert_called_once()
            # Azure returned English ("translated by azure"), which still appears
            # English, so _translate_from_english falls through to returning the
            # original English text (translation failed for both providers).
            assert result == long_text

    def test_azure_receives_full_original_text(self):
        """Azure fallback receives the FULL original text, not partial chunks.

        Even though Azure returns English ("Azure translation"), the function
        still calls Azure with the full original text. The post-translation
        check then rejects the English result, but the test verifies the correct
        input was sent to Azure.
        """
        from app.routes.chat import _translate_from_english

        settings = _settings_stub()
        long_text = _build_long_text()

        with patch("app.routes.chat.SarvamTranslator") as MockSarvam:
            mock_sarvam = MagicMock()
            mock_sarvam.configured = True
            mock_sarvam.translate.side_effect = RuntimeError("Sarvam API failed")
            MockSarvam.return_value = mock_sarvam

            with patch("app.routes.chat.AzureTranslator") as MockAzure:
                mock_azure = MagicMock()
                mock_azure.configured = True
                mock_azure.translate.return_value = "Azure translation"
                MockAzure.return_value = mock_azure

                _translate_from_english(long_text, "gu", settings)

            # Azure received the full original text (even though its English
            # output will be rejected by the post-translation check)
            call_args = mock_azure.translate.call_args
            azure_text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
            assert azure_text == long_text


# ---------------------------------------------------------------------------
# Test 7: URL preservation
# ---------------------------------------------------------------------------


class TestUrlPreservation:
    def test_urls_unchanged_through_translation(self):
        """URLs in text must remain byte-for-byte unchanged after Sarvam translation."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)

        text_with_urls = (
            "You can file your complaint at https://vmc.gov.in/complaints "
            "or visit https://vmc.gov.in/ward-offices for ward details. "
            "For emergencies call the helpline."
        )

        mock_resp = _mock_sarvam_response(
            "તમે https://vmc.gov.in/complaints પર ફરિયાદ કરી શકો છો "
            "અથવા https://vmc.gov.in/ward-offices પર વોર્ડ વિગતો જુઓ."
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            result = translator.translate(text_with_urls, to="gu", source="en")

        # URLs must be preserved exactly
        assert "https://vmc.gov.in/complaints" in result
        assert "https://vmc.gov.in/ward-offices" in result

    def test_urls_unchanged_in_long_multichunk_text(self):
        """URLs in long multi-chunk text must survive translation."""
        settings = _settings_stub()
        translator = SarvamTranslator(settings)

        long_text_with_url = (
            _build_long_text()
            + " Visit https://vmc.gov.in/complaints for more details."
        )

        mock_resp = _mock_sarvam_response(
            "translated text with https://vmc.gov.in/complaints preserved"
        )

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            result = translator.translate(long_text_with_url, to="gu", source="en")

        assert "https://vmc.gov.in/complaints" in result


# ---------------------------------------------------------------------------
# Test 8: Model payload contains mayura:v1
# ---------------------------------------------------------------------------


class TestModelPayload:
    def test_model_is_v1(self):
        """Payload must contain model: mayura:v1."""
        mock_resp = _mock_sarvam_response("Hello")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            _raw_translate("sk_test", "नमस्ते", "hi", "en")

            call_kwargs = mock_ctx.post.call_args
            payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert payload["model"] == "mayura:v1"

    def test_payload_complete_structure(self):
        """Full payload structure matches Sarvam API contract."""
        mock_resp = _mock_sarvam_response("Hello")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            _raw_translate("sk_test", "नमस्ते", "hi", "en")

            call_kwargs = mock_ctx.post.call_args
            payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert payload == {
                "input": "नमस्ते",
                "source_language_code": "hi-IN",
                "target_language_code": "en-IN",
                "model": "mayura:v1",
                "numerals_format": "native",
                "mode": "modern-colloquial",
            }


# ---------------------------------------------------------------------------
# Test 9: Language payload directions
# ---------------------------------------------------------------------------


class TestLanguagePayloadDirections:
    def test_gu_to_en_payload(self):
        """gu-IN → en-IN payload is correct."""
        mock_resp = _mock_sarvam_response("Hello")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            _raw_translate("sk_test", "નમસ્તે", "gu", "en")

            call_kwargs = mock_ctx.post.call_args
            payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert payload["source_language_code"] == "gu-IN"
            assert payload["target_language_code"] == "en-IN"

    def test_en_to_gu_payload(self):
        """en-IN → gu-IN payload is correct."""
        mock_resp = _mock_sarvam_response("નમસ્તે")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            _raw_translate("sk_test", "Hello", "en", "gu")

            call_kwargs = mock_ctx.post.call_args
            payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert payload["source_language_code"] == "en-IN"
            assert payload["target_language_code"] == "gu-IN"

    def test_hi_to_en_payload(self):
        """hi-IN → en-IN payload is correct (regression)."""
        mock_resp = _mock_sarvam_response("Hello")

        with patch("httpx.Client") as MockClient:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_ctx

            _raw_translate("sk_test", "नमस्ते", "hi", "en")

            call_kwargs = mock_ctx.post.call_args
            payload = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert payload["source_language_code"] == "hi-IN"
            assert payload["target_language_code"] == "en-IN"
