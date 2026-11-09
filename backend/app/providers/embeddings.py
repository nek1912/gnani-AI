import re
import time
from collections import deque
from functools import lru_cache

import httpx

from app.config import EMBED_DIMS, REQUEST_TIMEOUT_S, Settings, get_settings
from app.key_rotator import KeyRotator

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _http_status_of(exc: Exception) -> int | None:
    """Best-effort HTTP status extraction for retry decisions.

    httpx errors carry .response.status_code; the Jina inner call raises
    RuntimeError("Jina embedding HTTP {status}: ...") instead, so parse
    the status back out of the message. Returns None when the error has
    no HTTP status (non-HTTP failures are retried with backoff).
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    m = re.search(r"HTTP (\d{3})", str(exc))
    return int(m.group(1)) if m else None

# Jina free tier: 100k tokens/minute. Pace below that to avoid persistent 429s.
_TPM_LIMIT = 85_000
_TPM_WINDOW_S = 60.0


def _approx_tokens(text: str) -> int:
    # Rough tokenizer-free estimate (~4 chars/token) for client-side throttling.
    return max(1, len(text) // 4)


class JinaEmbeddingProvider:
    def __init__(self, settings: Settings):
        self._endpoint = "https://api.jina.ai/v1/embeddings"
        self._model = settings.jina_embed_model or getattr(settings, "embedding_model", "jina-embeddings-v3") or "jina-embeddings-v3"
        self._max_attempts = 5
        self._base_delay = 2.0
        self._token_log: deque[tuple[float, int]] = deque()
        keys = settings.jina_keys
        self._rotator = KeyRotator(keys, name="jina") if keys else None

    @property
    def _key(self) -> str:
        """Return the current active key (for backward compat)."""
        if self._rotator:
            return self._rotator.current_key
        return ""

    def _throttle(self, n_tokens: int) -> None:
        """Block until sending `n_tokens` keeps us under the TPM budget."""
        now = time.monotonic()
        cutoff = now - _TPM_WINDOW_S
        while self._token_log and self._token_log[0][0] < cutoff:
            self._token_log.popleft()
        used = sum(t for _, t in self._token_log)
        if used + n_tokens > _TPM_LIMIT:
            wait = _TPM_WINDOW_S - (now - self._token_log[0][0]) + 0.5
            if wait > 0:
                time.sleep(min(wait, _TPM_WINDOW_S))
            self._throttle(n_tokens)
        else:
            self._token_log.append((time.monotonic(), n_tokens))

    def _embed_batch(self, texts: list[str], client: httpx.Client, task: str = "retrieval.passage") -> list[list[float]]:
        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                def _call_with_key(key: str) -> list[list[float]]:
                    r = client.post(
                        self._endpoint,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model,
                            "input": texts,
                            "dimensions": EMBED_DIMS,
                            "task": task,
                            "truncate": True,
                        },
                    )
                    if r.status_code >= 400:
                        raise RuntimeError(f"Jina embedding HTTP {r.status_code}: {r.text[:600]}")
                    r.raise_for_status()
                    data = r.json()["data"]
                    data.sort(key=lambda x: x["index"])
                    return [item["embedding"] for item in data]

                if self._rotator:
                    return self._rotator.try_keys(_call_with_key)
                return _call_with_key(self._key)
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError, RuntimeError) as exc:
                last_exc = exc
                status = _http_status_of(exc)
                if status is not None and status not in _RETRYABLE_STATUS:
                    raise
                if attempt < self._max_attempts - 1:
                    time.sleep(self._base_delay * (2 ** attempt))
        raise last_exc  # type: ignore[misc]

    def embed_texts(self, texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
        if not texts:
            return []
        # Jina supports batch embedding - process in chunks of 100.
        # Pace batches by approximate tokens to stay under the free-tier TPM cap.
        all_embeddings = []
        with httpx.Client(timeout=60.0) as client:
            for i in range(0, len(texts), 100):
                batch = texts[i:i+100]
                self._throttle(sum(_approx_tokens(t) for t in batch))
                embeddings = self._embed_batch(batch, client, task=task)
                all_embeddings.extend(embeddings)
                if i + 100 < len(texts):
                    time.sleep(0.2)
        return all_embeddings


class GeminiEmbeddingProvider:
    def __init__(self, settings: Settings):
        self._key = settings.gemini_api_key
        if not settings.embed_model:
            # Fail fast: without EMBED_MODEL the endpoint URL contains an
            # empty model segment (".../models/:embedContent") and every
            # request 404s. NOTE: EMBED_MODEL (Gemini model id) is NOT
            # EMBEDDING_MODEL (Jina model name) — see config.py.
            raise RuntimeError("EMBED_MODEL not configured for Gemini embeddings")
        self._endpoint = ("https://generativelanguage.googleapis.com/v1beta/models/"
                          f"{settings.embed_model}:embedContent")
        self._max_attempts = 3
        self._base_delay = 1.0

    def _embed_single(self, text: str, client: httpx.Client) -> list[float]:
        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                r = client.post(
                    f"{self._endpoint}?key={self._key}",
                    json={
                        "content": {"parts": [{"text": text}]},
                        "output_dimensionality": EMBED_DIMS,
                    },
                )
                r.raise_for_status()
                values = r.json()["embedding"]["values"]
                if len(values) != EMBED_DIMS:
                    raise ValueError(f"unexpected dims {len(values)}")
                return values
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in _RETRYABLE_STATUS:
                    raise
                if attempt < self._max_attempts - 1:
                    time.sleep(self._base_delay * (2 ** attempt))
        raise last_exc  # type: ignore[misc]

    def embed_texts(self, texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
        out: list[list[float]] = []
        with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
            for text in texts:
                out.append(self._embed_single(text, client))
        return out


@lru_cache(maxsize=1)
def get_embedding_provider():
    """Process-wide singleton. The route MUST use this — constructing a fresh
    provider per request would defeat the anchor-store cache (P0-1)."""
    settings = get_settings()
    # Prefer Jina if API key is available, fall back to Gemini
    if settings.jina_api_key:
        return JinaEmbeddingProvider(settings)
    return GeminiEmbeddingProvider(settings)
