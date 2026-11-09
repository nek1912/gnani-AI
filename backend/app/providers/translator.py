"""Azure Translator provider for multilingual query normalization (Phase 10).

The authoritative corpus is English, so a non-English user query is translated
to English *before* embedding / classification / lexical retrieval. The
original query language is preserved for answer generation (the LLM answers in
the user's language). Translating only the retrieval-side query — never the
documents — keeps the frozen corpus untouched and avoids re-ingestion.

All failures degrade gracefully: if the translator is unconfigured or an
HTTP/parse error occurs, the original text is returned so retrieval still runs
(weaker, but never crashing).
"""
from __future__ import annotations

from functools import lru_cache

import httpx

from app.config import REQUEST_TIMEOUT_S, get_settings


class TranslatorError(RuntimeError):
    pass


@lru_cache(maxsize=1024)
def _cached_translate(key: str, text: str, to: str, source: str) -> str:
    """Translate with a stable cache key; returns original text on any failure.

    ``key`` is the translator subscription key so different deployments don't
    share cache entries; it is never logged or returned.
    """
    if not text.strip():
        return text
    endpoint = get_settings().azure_translator_endpoint.rstrip("/")
    params = {"api-version": "3.0", "to": to}
    if source:
        params["from"] = source
    headers = {
        "Ocp-Apim-Subscription-Key": get_settings().azure_translator_key,
        "Ocp-Apim-Subscription-Region": get_settings().azure_translator_region,
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
            resp = client.post(
                f"{endpoint}/translate",
                params=params,
                headers=headers,
                json=[{"Text": text}],
            )
            resp.raise_for_status()
            data = resp.json()
            translated = data[0]["translations"][0]["text"]
            return translated if translated else text
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return text


class AzureTranslator:
    """Thin Azure Translator client. Configured when key + endpoint are set."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self.settings.azure_translator_key
                    and self.settings.azure_translator_endpoint)

    def translate(self, text: str, to: str = "en", source: str | None = None) -> str:
        if not self.configured:
            return text
        return _cached_translate(self.settings.azure_translator_key, text, to, source or "")
