from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.providers.embeddings import GeminiEmbeddingProvider, JinaEmbeddingProvider
from app.config import Settings


def _make_provider() -> GeminiEmbeddingProvider:
    return GeminiEmbeddingProvider(Settings(
        groq_api_key="test", gemini_api_key="test",
        supabase_url="http://test", supabase_service_key="test",
        embed_model="gemini-embedding-2",
    ))


def test_retry_on_rate_limit():
    """Verify retry logic handles 429 errors."""
    provider = _make_provider()
    call_count = [0]

    def mock_post(self, url, **kwargs):
        call_count[0] += 1
        if call_count[0] < 3:
            response = MagicMock()
            response.status_code = 429
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "rate limited", request=MagicMock(), response=response
            )
            return response
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"embedding": {"values": [0.1] * 768}}
        return response

    with patch("httpx.Client.post", mock_post):
        result = provider.embed_texts(["test text"])
        assert len(result) == 1
        assert len(result[0]) == 768
        assert call_count[0] == 3


def test_retry_on_server_error():
    """Verify retry logic handles 500 errors."""
    provider = _make_provider()
    call_count = [0]

    def mock_post(self, url, **kwargs):
        call_count[0] += 1
        if call_count[0] < 2:
            response = MagicMock()
            response.status_code = 500
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "server error", request=MagicMock(), response=response
            )
            return response
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"embedding": {"values": [0.1] * 768}}
        return response

    with patch("httpx.Client.post", mock_post):
        result = provider.embed_texts(["test text"])
        assert len(result) == 1
        assert call_count[0] == 2


def test_non_retryable_error_raises_immediately():
    """400/401 errors should not be retried."""
    provider = _make_provider()
    call_count = [0]

    def mock_post(self, url, **kwargs):
        call_count[0] += 1
        response = MagicMock()
        response.status_code = 400
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "bad request", request=MagicMock(), response=response
        )
        return response

    with patch("httpx.Client.post", mock_post):
        with pytest.raises(httpx.HTTPStatusError):
            provider.embed_texts(["test text"])
        assert call_count[0] == 1


def test_retry_exhausted_raises_last_error():
    """After max retries, the last exception is raised."""
    provider = _make_provider()

    def mock_post(self, url, **kwargs):
        response = MagicMock()
        response.status_code = 429
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=response
        )
        return response

    with patch("httpx.Client.post", mock_post):
        with pytest.raises(httpx.HTTPStatusError):
            provider.embed_texts(["test text"])


def test_retry_on_timeout():
    """Verify retry logic handles connection timeouts."""
    provider = _make_provider()
    call_count = [0]

    def mock_post(self, url, **kwargs):
        call_count[0] += 1
        if call_count[0] < 2:
            raise httpx.TimeoutException("timeout")
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"embedding": {"values": [0.1] * 768}}
        return response

    with patch("httpx.Client.post", mock_post):
        result = provider.embed_texts(["test text"])
        assert len(result) == 1
        assert call_count[0] == 2


def test_success_on_first_attempt():
    """No retries when the first call succeeds."""
    provider = _make_provider()
    call_count = [0]

    def mock_post(self, url, **kwargs):
        call_count[0] += 1
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {"embedding": {"values": [0.1] * 768}}
        return response

    with patch("httpx.Client.post", mock_post):
        result = provider.embed_texts(["test text"])
        assert len(result) == 1
        assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Jina provider: HTTP errors surface as RuntimeError (not httpx.HTTPStatusError),
# so the retry loop must handle RuntimeError explicitly. Regression tests.
# ---------------------------------------------------------------------------

def _make_jina_provider() -> JinaEmbeddingProvider:
    # Pin jina_api_key_2="" so the real backend/.env value (read by
    # pydantic-settings for any field without an explicit kwarg) cannot
    # add a second rotation key and change call counts.
    return JinaEmbeddingProvider(Settings(
        groq_api_key="test", gemini_api_key="test",
        supabase_url="http://test", supabase_service_key="test",
        jina_api_key="k1", jina_api_key_2="",
    ))


def test_jina_retry_on_429_then_success():
    """Jina 429s are retried with backoff until success."""
    provider = _make_jina_provider()
    call_count = [0]

    def mock_post(self, url, **kwargs):
        call_count[0] += 1
        response = MagicMock()
        if call_count[0] < 3:
            response.status_code = 429
            response.text = "rate limited"
            return response
        response.status_code = 200
        response.text = "ok"
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [{"index": 0, "embedding": [0.1] * 768}]}
        return response

    with patch("httpx.Client.post", mock_post), patch("time.sleep", return_value=None):
        result = provider.embed_texts(["hello"])
        assert len(result) == 1
        assert len(result[0]) == 768
        assert call_count[0] == 3


def test_jina_no_retry_on_400():
    """Jina 400s are not retryable — fail fast without backoff."""
    provider = _make_jina_provider()
    call_count = [0]

    def mock_post(self, url, **kwargs):
        call_count[0] += 1
        response = MagicMock()
        response.status_code = 400
        response.text = "bad request"
        return response

    with patch("httpx.Client.post", mock_post), patch("time.sleep", return_value=None):
        with pytest.raises(RuntimeError):
            provider.embed_texts(["hello"])
        assert call_count[0] == 1
