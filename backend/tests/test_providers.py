import httpx

from app.config import Settings
from app.providers.embeddings import GeminiEmbeddingProvider
from app.providers.groq_llm import GroqLLMProvider


def test_embed_returns_768_per_text(respx_mock):
    body = {"embedding": {"values": [0.1] * 768}}
    respx_mock.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent").mock(
        return_value=httpx.Response(200, json=body)
    )
    provider = GeminiEmbeddingProvider(Settings(gemini_api_key="k", groq_api_key="g",
        supabase_url="u", supabase_service_key="s", embed_model="gemini-embedding-2"))
    out = provider.embed_texts(["a", "b"])
    assert len(out) == 2 and len(out[0]) == 768


def test_groq_generate(respx_mock):
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
    )
    p = GroqLLMProvider(Settings(gemini_api_key="k", groq_api_key="g",
        supabase_url="u", supabase_service_key="s"))
    assert p.generate("sys", "user") == "hi"
