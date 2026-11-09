"""Groq LLM provider with API key rotation."""

import json
import time
import logging
from collections.abc import Generator

logger = logging.getLogger(__name__)

import httpx

from app.config import GENERATION_MAX_TOKENS, REQUEST_TIMEOUT_S, Settings
from app.key_rotator import KeyRotator

_URL = "https://api.groq.com/openai/v1/chat/completions"


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


class GroqLLMProvider:
    def __init__(self, settings: Settings):
        keys = settings.groq_keys
        self._rotator = KeyRotator(keys, name="groq") if keys else None
        self._key = settings.groq_api_key  # fallback for single-key compat
        self._model = settings.groq_model
        self._models = settings.groq_model_list

    def _get_key(self) -> str:
        return self._rotator.current_key if self._rotator else self._key

    def generate(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = GENERATION_MAX_TOKENS) -> str:
        if self._rotator:
            return self._rotator.try_keys(lambda key: self._do_generate(key, system, user, temperature, max_tokens))
        return self._do_generate(self._key, system, user, temperature, max_tokens)

    def _do_generate(self, key: str, system: str, user: str, temperature: float, max_tokens: int = GENERATION_MAX_TOKENS) -> str:
        models_to_try = list(dict.fromkeys([self._model] + self._models))
        last_exc: Exception | None = None
        for model in models_to_try:
            logger.info(f"Calling Groq LLM with model: {model}")
            start_time = time.time()
            try:
                r = httpx.post(
                    _URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                    timeout=REQUEST_TIMEOUT_S,
                )
                logger.info(f"Groq LLM ({model}) response time: {time.time() - start_time:.2f}s, status: {r.status_code}")
                if r.status_code == 200:
                    resp_data = r.json()
                    content = resp_data["choices"][0]["message"]["content"]
                    usage = resp_data.get("usage", {})
                    if usage:
                        logger.info(
                            "Groq usage: prompt_tokens=%s, completion_tokens=%s, total_tokens=%s",
                            usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
                        )
                    return content
                logger.error(f"Groq API Error Body ({model}): {r.text}")
                r.raise_for_status()
            except Exception as e:
                last_exc = e
                category = _classify_error(e)
                logger.warning("Groq model %s failed [%s]: %s — trying next fallback model", model, category, e)
        raise last_exc or RuntimeError("All Groq models failed")

    def generate_stream(self, system: str, user: str,
                        temperature: float = 0.0) -> Generator[str, None, None]:
        """Yield text tokens as they arrive from Groq's streaming API."""
        key = self._get_key()
        try:
            yield from self._do_stream(key, system, user, temperature)
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
            if not self._rotator:
                raise
            # Try next key
            for key in self._rotator._keys:
                if key == self._get_key():
                    continue
                try:
                    yield from self._do_stream(key, system, user, temperature)
                    return
                except Exception:
                    continue
            raise

    def _do_stream(self, key: str, system: str, user: str,
                   temperature: float) -> Generator[str, None, None]:
        with httpx.stream(
            "POST", _URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": self._model, "temperature": temperature, "stream": True,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
