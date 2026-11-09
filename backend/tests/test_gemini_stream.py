"""Regression tests for Gemini generate_stream (P0: AttributeError on _stream_url)."""
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.providers.gemini_llm import GeminiLLMProvider


def _settings(**overrides) -> Settings:
    base = dict(
        groq_api_key="test", gemini_api_key="key",
        supabase_url="http://test", supabase_service_key="test",
        gemini_model="m1", gemini_fallback_model="m2",
    )
    base.update(overrides)
    return Settings(**base)


class _FakeStreamResp:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield 'data: {"candidates": [{"content": {"parts": [{"text": "hel"}]}}]}'
        yield ''
        yield 'not-json-at-all'
        yield 'data: {"candidates": [{"content": {"parts": [{"text": "lo"}]}}]}'
        yield 'data: [DONE]'


def test_generate_stream_yields_tokens():
    provider = GeminiLLMProvider(_settings())
    with patch("app.providers.gemini_llm.httpx.stream", return_value=_FakeStreamResp()):
        assert "".join(provider.generate_stream("sys", "hi")) == "hello"


def test_generate_stream_falls_back_to_next_model():
    provider = GeminiLLMProvider(_settings())
    urls = []

    def fake_stream(method, url, **kwargs):
        urls.append(url)
        if "m1" in url:
            raise httpx.ConnectError("down")
        return _FakeStreamResp()

    with patch("app.providers.gemini_llm.httpx.stream", side_effect=fake_stream):
        assert "".join(provider.generate_stream("sys", "hi")) == "hello"
    assert any("m1" in u for u in urls) and any("m2" in u for u in urls)


def test_generate_stream_requires_key():
    provider = GeminiLLMProvider(_settings(gemini_api_key=""))
    with pytest.raises(RuntimeError):
        list(provider.generate_stream("sys", "hi"))
