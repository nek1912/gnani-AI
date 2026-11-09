"""LLM failure injection tests — provider fallback, retryable vs non-retryable errors."""
import re

import httpx
import pytest
import respx

from app.config import Settings
from app.llm_fallback import AllProvidersFailedError, grounded_answer
from app.providers.gemini_llm import GeminiLLMProvider
from app.providers.groq_llm import GroqLLMProvider

S = lambda: Settings(
    gemini_api_key="k", groq_api_key="g",
    supabase_url="u", supabase_service_key="s",
    gemini_model="gemini-2.5-flash")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = re.compile(r"https://generativelanguage\.googleapis\.com/v1beta/models/gemini-[\d\.]+-flash:generateContent\?key=.*")


def _groq_response(code, body=None):
    return httpx.Response(code, json=body or {"error": "test"})


def _gemini_success(text="fallback ok"):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


# ── Retryable HTTP errors → fallback ────────────────────────────────────

@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
@respx.mock
def test_retryable_http_falls_back_to_gemini(code, respx_mock):
    respx_mock.post(GROQ_URL).mock(return_value=_groq_response(code))
    respx_mock.post(GEMINI_URL).mock(return_value=_gemini_success())
    out = grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
    assert out == "fallback ok"


@respx.mock
def test_timeout_falls_back_to_gemini(respx_mock):
    respx_mock.post(GROQ_URL).mock(side_effect=httpx.TimeoutException("timeout"))
    respx_mock.post(GEMINI_URL).mock(return_value=_gemini_success())
    out = grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
    assert out == "fallback ok"


@respx.mock
def test_connection_error_falls_back_to_gemini(respx_mock):
    respx_mock.post(GROQ_URL).mock(side_effect=httpx.ConnectError("refused"))
    respx_mock.post(GEMINI_URL).mock(return_value=_gemini_success())
    out = grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
    assert out == "fallback ok"


# ── Non-retryable HTTP errors → raise immediately ──────────────────────

@pytest.mark.parametrize("code", [401, 403])
@respx.mock
def test_non_retryable_http_raises(code, respx_mock):
    respx_mock.post(GROQ_URL).mock(return_value=_groq_response(code))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")


# ── Both providers fail → AllProvidersFailedError ──────────────────────

@respx.mock
def test_both_retryable_fail_raises_all_providers(respx_mock):
    respx_mock.post(GROQ_URL).mock(return_value=_groq_response(429))
    respx_mock.post(GEMINI_URL).mock(return_value=_groq_response(429))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")


@respx.mock
def test_timeout_then_429_raises_all_providers(respx_mock):
    respx_mock.post(GROQ_URL).mock(side_effect=httpx.TimeoutException("timeout"))
    respx_mock.post(GEMINI_URL).mock(return_value=_groq_response(429))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")


@respx.mock
def test_connection_error_then_timeout_raises_all_providers(respx_mock):
    respx_mock.post(GROQ_URL).mock(side_effect=httpx.ConnectError("refused"))
    respx_mock.post(GEMINI_URL).mock(side_effect=httpx.TimeoutException("timeout"))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")


# ── Invalid/malformed responses → fallback ──────────────────────────────

@respx.mock
def test_groq_invalid_json_raises_not_retryable(respx_mock):
    respx_mock.post(GROQ_URL).mock(return_value=httpx.Response(200, text="not json"))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")


@respx.mock
def test_groq_missing_choices_raises_not_retryable(respx_mock):
    respx_mock.post(GROQ_URL).mock(return_value=httpx.Response(200, json={"data": "nope"}))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")


@respx.mock
def test_groq_empty_content_returns_empty_string(respx_mock):
    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}))
    out = grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
    assert out == ""


# ── Primary success → no fallback call ─────────────────────────────────

@respx.mock
def test_primary_success_no_fallback(respx_mock):
    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "primary ok"}}]}))
    out = grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
    assert out == "primary ok"
    assert not respx_mock.calls.call_count or respx_mock.calls.call_count == 1


# ── Non-retryable from fallback also raises ────────────────────────────

@respx.mock
def test_retryable_then_non_retryable_raises(respx_mock):
    respx_mock.post(GROQ_URL).mock(return_value=_groq_response(429))
    respx_mock.post(GEMINI_URL).mock(return_value=_groq_response(401))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")


# ── AllProvidersFailedError message contains both providers ─────────────

@respx.mock
def test_all_providers_error_message_contains_both_names(respx_mock):
    respx_mock.post(GROQ_URL).mock(return_value=_groq_response(500))
    respx_mock.post(GEMINI_URL).mock(return_value=_groq_response(500))
    with pytest.raises(AllProvidersFailedError, match="groq.*gemini"):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
