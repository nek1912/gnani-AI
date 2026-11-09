"""Tests for SarvamChatProvider."""
import pytest
from unittest.mock import MagicMock, patch

from app.providers.sarvam_chat import SarvamChatProvider, SarvamProviderError
from app.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test-groq",
        "gemini_api_key": "test-gemini",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test-key",
        "sarvam_api_key": "sk_test_sarvam_1",
        "sarvam_api_key_2": "sk_test_sarvam_2",
        "sarvam_chat_model": "sarvam-105b",
        "sarvam_chat_url": "https://api.sarvam.ai/v1/chat/completions",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestSarvamChatProvider:
    def test_generate_returns_content(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "नमस्ते, मैं आपकी मदद कर सकता हूँ।"}}]
        }
        with patch("httpx.post", return_value=mock_response):
            result = provider.generate("System prompt", "User question")
        assert result == "नमस्ते, मैं आपकी मदद कर सकता हूँ।"

    def test_generate_rotates_keys_on_429_with_backoff(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        # 429 on key1, success on key2
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "rate limited"
        resp_429.json.return_value = {"error": {"message": "rate limited"}}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "Success on key 2"}}]
        }
        with patch("httpx.post", side_effect=[resp_429, resp_200]):
            with patch("time.sleep"):  # Skip actual backoff in tests
                result = provider.generate("System", "User")
        assert result == "Success on key 2"

    def test_422_does_not_rotate_keys(self):
        """422 = bad request, not bad key. Rotating won't help."""
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = "invalid parameters"
        mock_response.json.return_value = {"error": {"message": "invalid"}}
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(SarvamProviderError) as exc_info:
                provider.generate("System", "User")
            assert exc_info.value.retryable is False

    def test_403_invalid_key_rotates(self):
        """403 + invalid_api_key → try next key."""
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "forbidden"
        resp_403.json.return_value = {"error": {"code": "invalid_api_key", "message": "bad key"}}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "Success on key 2"}}]
        }
        with patch("httpx.post", side_effect=[resp_403, resp_200]):
            result = provider.generate("System", "User")
        assert result == "Success on key 2"

    def test_403_other_forbidden_does_not_rotate(self):
        """403 + other forbidden error → non-retryable, propagate."""
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "forbidden"
        mock_response.json.return_value = {"error": {"code": "permission_denied", "message": "no access"}}
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(SarvamProviderError) as exc_info:
                provider.generate("System", "User")
            assert exc_info.value.retryable is False

    def test_generate_sends_correct_headers_and_body(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        with patch("httpx.post", return_value=mock_response) as mock_post:
            provider.generate("System prompt", "User msg", temperature=0.5)
            call_kwargs = mock_post.call_args
            headers = call_kwargs[1].get("headers", call_kwargs.kwargs.get("headers", {}))
            assert "api-subscription-key" in headers
            assert headers["api-subscription-key"] == "sk_test_sarvam_1"
            assert "Authorization" not in headers
            body = call_kwargs[1].get("json", call_kwargs.kwargs.get("json", {}))
            assert body["model"] == "sarvam-105b"
            assert body["messages"][0]["content"] == "System prompt"
            assert body["temperature"] == 0.5
            assert body["reasoning_effort"] is None
            assert body["stream"] is False

    def test_all_keys_fail_raises_provider_error(self):
        settings = _make_settings()
        provider = SarvamChatProvider(settings)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "server error"
        mock_response.json.return_value = {"error": {"message": "server error"}}
        with patch("httpx.post", return_value=mock_response):
            with pytest.raises(SarvamProviderError):
                provider.generate("System", "User")