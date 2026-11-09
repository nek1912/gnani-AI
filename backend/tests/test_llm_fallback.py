import httpx
import pytest
import re
import respx

from app.config import Settings
from app.llm_fallback import AllProvidersFailedError, grounded_answer
from app.providers.gemini_llm import GeminiLLMProvider
from app.providers.groq_llm import GroqLLMProvider

S = lambda: Settings(gemini_api_key="k", groq_api_key="g", supabase_url="u", supabase_service_key="s", gemini_model="gemini-2.5-flash")

@respx.mock
def test_falls_back_to_gemini_on_429():
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": "rate"}))
    respx.post(re.compile(r"https://generativelanguage\.googleapis\.com/v1beta/models/gemini-[\d\.]+-flash:generateContent\?key=.*")).mock(
        return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "fb"}]}}]}))
    out = grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
    assert out == "fb"

@respx.mock
def test_raises_when_both_fail():
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={}))
    respx.post(re.compile(r"https://generativelanguage\.googleapis\.com/v1beta/models/gemini-[\d\.]+-flash:generateContent\?key=.*")).mock(
        return_value=httpx.Response(429, json={}))
    with pytest.raises(AllProvidersFailedError):
        grounded_answer(GroqLLMProvider(S()), GeminiLLMProvider(S()), "sys", "user")
