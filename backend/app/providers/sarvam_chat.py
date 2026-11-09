"""Sarvam AI chat completions provider (OpenAI-compatible API)."""
from __future__ import annotations

import httpx
import logging
import time

from app.config import Settings
from app.key_rotator import KeyRotator

logger = logging.getLogger(__name__)


class SarvamProviderError(Exception):
    """Dedicated exception for Sarvam provider failures.

    Subclasses distinguish retryable from non-retryable errors:
    - Retryable: 403 (invalid_api_key), 429, 500, 503, timeout
    - Non-retryable: 400, 422, malformed response, programming errors
    """

    def __init__(self, message: str, status_code: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English, ~2 for Devanagari."""
    return len(text) // 3


class SarvamChatProvider:
    """Sarvam-105B chat completions adapter.

    Uses the OpenAI-compatible endpoint at api.sarvam.ai.
    Auth: ``api-subscription-key: <key>`` header only.
    Reasoning is disabled (reasoning_effort=None) for latency-sensitive RAG.
    """

    def __init__(self, settings: Settings) -> None:
        keys = settings.sarvam_keys
        if not keys:
            raise ValueError("No Sarvam API keys configured")
        self._rotator = KeyRotator(keys, name="sarvam")
        self._model = settings.sarvam_chat_model
        self._url = settings.sarvam_chat_url

    def generate(
        self, system: str, user: str, temperature: float = 0.0
    ) -> str:
        """Non-streaming generation. Primary MVP path."""
        # Log prompt size for optimization
        sys_tokens = _estimate_tokens(system)
        user_tokens = _estimate_tokens(user)
        total_input_tokens = sys_tokens + user_tokens
        logger.info(
            "Sarvam prompt: system=%d chars (~%d tokens), user=%d chars (~%d tokens), total ~%d tokens",
            len(system), sys_tokens, len(user), user_tokens, total_input_tokens,
        )
        
        start_time = time.monotonic()
        last_error: SarvamProviderError | None = None
        keys = self._rotator._keys
        for key in keys:
            try:
                result = self._call_api(key, system, user, temperature)
                elapsed = time.monotonic() - start_time
                output_tokens = _estimate_tokens(result)
                logger.info(
                    "Sarvam response: %.1fs, output ~%d tokens, total ~%d tokens",
                    elapsed, output_tokens, total_input_tokens + output_tokens,
                )
                return result
            except SarvamProviderError as exc:
                last_error = exc
                if not exc.retryable:
                    raise  # 400, 422 — don't rotate keys
                # 429 → bounded backoff before trying next key
                if exc.status_code == 429:
                    time.sleep(1.0)
                continue
        raise last_error  # type: ignore[misc]

    def _call_api(
        self,
        key: str,
        system: str,
        user: str,
        temperature: float,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
            "api-subscription-key": key,
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "reasoning_effort": None,
            "max_tokens": 2048,
            "stream": False,
        }
        try:
            resp = httpx.post(self._url, json=body, headers=headers, timeout=(30.0, 120.0))
        except httpx.TimeoutException as exc:
            raise SarvamProviderError(f"Timeout: {exc}", retryable=True) from exc

        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if not choices or not choices[0].get("message", {}).get("content"):
                raise SarvamProviderError("Empty response from Sarvam", retryable=False)
            
            # Log usage if available
            usage = data.get("usage", {})
            if usage:
                logger.info(
                    "Sarvam usage: prompt_tokens=%s, completion_tokens=%s, total_tokens=%s",
                    usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"),
                )
            
            return choices[0]["message"]["content"]

        # Classify error
        if resp.status_code == 422:
            raise SarvamProviderError(
                f"Invalid request (422): {resp.text[:200]}", status_code=422, retryable=False
            )
        if resp.status_code == 400:
            raise SarvamProviderError(
                f"Bad request (400): {resp.text[:200]}", status_code=400, retryable=False
            )
        if resp.status_code == 403:
            # 403 can mean invalid key OR other forbidden error
            # Inspect error.code if available
            try:
                err_body = resp.json()
                err_code = err_body.get("error", {}).get("code", "")
                if err_code == "invalid_api_key":
                    raise SarvamProviderError(
                        "Invalid API key (403)", status_code=403, retryable=True
                    )
            except (ValueError, KeyError):
                pass
            raise SarvamProviderError(
                f"Forbidden (403): {resp.text[:200]}", status_code=403, retryable=False
            )
        if resp.status_code in (429, 500, 503):
            raise SarvamProviderError(
                f"Provider error ({resp.status_code}): {resp.text[:200]}",
                status_code=resp.status_code,
                retryable=True,
            )
        raise SarvamProviderError(
            f"Unexpected status {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
            retryable=False,
        )