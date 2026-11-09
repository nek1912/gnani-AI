import json
from collections.abc import Generator

import httpx

from app.config import REQUEST_TIMEOUT_S, Settings


import logging

logger = logging.getLogger(__name__)


def _classify_error(exc: Exception) -> str:
    """Classify an exception into a human-readable error category."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "transient_connect"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return "rate_limit"
        if 500 <= code < 600:
            return f"provider_5xx({code})"
        if code == 404:
            return "model_not_found"
        return f"http_{code}"
    return type(exc).__name__


class GeminiLLMProvider:
    def __init__(self, settings: Settings):
        self._key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._fallback_models = settings.gemini_model_list

    def generate(self, system: str, user: str, temperature: float = 0.0) -> str:
        if not self._key:
            raise RuntimeError("Gemini API key not configured")

        models_to_try = list(dict.fromkeys([self._model] + self._fallback_models))
        last_exc: Exception | None = None

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                r = httpx.post(
                    f"{url}?key={self._key}",
                    json={
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": {"temperature": temperature},
                    },
                    timeout=REQUEST_TIMEOUT_S,
                )
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as exc:
                last_exc = exc
                category = _classify_error(exc)
                logger.warning(
                    "Gemini model %s failed [%s]: %s — trying next fallback model",
                    model, category, str(exc)[:200],
                )

        raise last_exc or RuntimeError("All Gemini models failed")

    def generate_stream(self, system: str, user: str,
                        temperature: float = 0.0) -> Generator[str, None, None]:
        """Yield text tokens as they arrive from Gemini's streaming API."""
        if not self._key:
            raise RuntimeError("Gemini API key not configured")

        models_to_try = list(dict.fromkeys([self._model] + self._fallback_models))
        last_exc: Exception | None = None
        for model in models_to_try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:streamGenerateContent?alt=sse&key={self._key}"
            )
            try:
                yield from self._do_stream(url, system, user, temperature)
                return
            except Exception as exc:
                last_exc = exc
                category = _classify_error(exc)
                logger.warning(
                    "Gemini stream model %s failed [%s]: %s — trying next fallback model",
                    model, category, str(exc)[:200],
                )
        raise last_exc or RuntimeError("All Gemini models failed")

    def _do_stream(self, url: str, system: str, user: str,
                   temperature: float) -> Generator[str, None, None]:
        with httpx.stream(
            "POST", url,
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": temperature},
            },
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                payload = line[6:] if line.startswith("data: ") else line
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    candidates = chunk.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            text = part.get("text")
                            if text:
                                yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
