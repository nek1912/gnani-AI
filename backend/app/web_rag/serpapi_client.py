"""
SerpApi web-search client (Google engine).

This module is the ONLY place where the application communicates
with SerpApi.

It mirrors the TavilyClient interface so the WebDiscoveryService can
treat all search engines identically behind a single, swappable
provider abstraction. To swap or add a search engine later, implement
a client with the same ``.search(...)`` signature and register it in
the provider factory (see ``app/web_rag/providers.py``).

Responsibilities:
- Send web-search requests (Google engine via SerpApi)
- Keep SerpApi credentials server-side
- Return raw search results in the unified shape:
      {"results": [ {url, title, content, raw_content?, score?, favicon?}, ... ]}
- Never generate answers
- Never perform RAG
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.web_rag.tavily_client import DOMAIN_SEARCH_CONTEXT, STATE_PORTALS

logger = logging.getLogger(__name__)

SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESULTS = 20
MAX_API_KEYS = 2
# Bounded site: filters appended to the Google query when the caller passes
# include/exclude domains (branch anchor scoping). Keeps q deterministic and
# short; the official-only stage still enforces filtering downstream.
MAX_DOMAIN_FILTERS = 8


class SerpApiConfigurationError(RuntimeError):
    """Raised when SerpApi is not configured."""


class SerpApiAPIError(RuntimeError):
    """Raised when the SerpApi request fails."""


class SerpApiClient:
    """SerpApi client (Google engine) with Tavily-compatible interface."""

    def __init__(
        self,
        api_key_1: Optional[str] = None,
        api_key_2: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.timeout = timeout
        if api_key_1 is not None or api_key_2 is not None:
            self.api_keys = [k for k in [api_key_1, api_key_2] if k and k.strip()]
        else:
            self.api_keys = self._load_api_keys()
        self.active_key_index = 0

    @staticmethod
    def _load_api_keys() -> List[str]:
        settings = get_settings()
        keys = []
        for value in (settings.serpapi_api_key_1, settings.serpapi_api_key_2):
            if value and value.strip():
                keys.append(value.strip())
        return keys[:MAX_API_KEYS]

    def is_configured(self) -> bool:
        return bool(self.api_keys)

    def require_configuration(self) -> None:
        if not self.api_keys:
            raise SerpApiConfigurationError(
                "No SerpApi API key is configured. "
                "Set SERPAPI_API_KEY_1 and optionally SERPAPI_API_KEY_2 in the backend .env file."
            )

    @staticmethod
    def _clean_domains(values: Any) -> list[str]:
        """Sanitize a domain list for site: filters (dedupe, bounded)."""
        seen: set[str] = set()
        cleaned: list[str] = []
        if not isinstance(values, (list, tuple)):
            return cleaned
        for value in values:
            domain = str(value or "").strip().lower()
            # Tolerate full URLs in branch specs: keep host only.
            if "://" in domain:
                domain = domain.split("://", 1)[1].split("/", 1)[0]
            domain = domain.split("/", 1)[0].split(":", 1)[0].removeprefix("www.").rstrip(".")
            if not domain or "." not in domain or domain in seen:
                continue
            seen.add(domain)
            cleaned.append(domain)
            if len(cleaned) >= MAX_DOMAIN_FILTERS:
                break
        return cleaned

    def _apply_domain_filters(
        self,
        enriched_query: str,
        include_domains: Optional[list[str]] = None,
        exclude_domains: Optional[list[str]] = None,
    ) -> str:
        """Honor the provider-contract domain params in the Google query.

        SerpApi has no server-side include_domains parameter (unlike
        Tavily), so anchor scoping is encoded as bounded site:/-site:
        clauses. The official-only stage still filters downstream.
        """
        includes = self._clean_domains(include_domains)
        excludes = self._clean_domains(exclude_domains)
        parts = [enriched_query]
        if includes:
            parts.append("(" + " OR ".join(f"site:{d}" for d in includes) + ")")
        if excludes:
            parts.append(" ".join(f"-site:{d}" for d in excludes))
        return " ".join(p for p in parts if p)

    def _build_enriched_query(
        self,
        query: str,
        domain: Optional[str] = None,
        state: Optional[str] = None,
    ) -> str:
        """Enrich search query with domain and state context.

        Reuses the same site-filter vocabulary as TavilyClient so both
        providers receive equivalent official-domain bias.
        """
        enriched_parts = [query]

        if state and state.lower() in STATE_PORTALS:
            state_keyword = STATE_PORTALS[state.lower()]["keywords"][0]
            enriched_parts.append(state_keyword)
        elif state:
            enriched_parts.append(state)

        if "india" not in query.lower() and "भारत" not in query:
            enriched_parts.append("India")

        enriched_query = " ".join(filter(None, enriched_parts))
        logger.info(f"SerpApi enriched query: '{query}' -> '{enriched_query}'")
        return enriched_query

    def search(
        self,
        query: str,
        *,
        domain: Optional[str] = None,
        state: Optional[str] = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        chunks_per_source: int = 3,
        include_domains: Optional[list[str]] = None,
        exclude_domains: Optional[list[str]] = None,
        search_depth: str = "advanced",
        include_raw_content: bool = True,
    ) -> Dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("SerpApi search query cannot be empty.")

        self.require_configuration()

        enriched_query = self._build_enriched_query(query, domain, state)
        enriched_query = self._apply_domain_filters(
            enriched_query, include_domains, exclude_domains
        )
        max_results = max(1, min(int(max_results), 20))

        errors: List[str] = []
        for key_index, api_key in enumerate(self.api_keys):
            params = {
                "engine": "google",
                "q": enriched_query,
                "num": max_results,
                "api_key": api_key,
                "gl": "in",
                "hl": "en",
            }
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(SERPAPI_SEARCH_URL, params=params)
            except httpx.RequestError as error:
                errors.append(f"key_{key_index + 1}: network error: {error}")
                continue

            if response.status_code == 429:
                body = response.text[:500]
                retry_after = response.headers.get("retry-after", "")
                extra = f" retry-after={retry_after}" if retry_after else ""
                detail = f": {body}" if body.strip() else ""
                errors.append(f"key_{key_index + 1}: HTTP 429 rate limited{extra}{detail}")
                continue
            if response.status_code >= 400:
                body = response.text[:1000]
                errors.append(f"key_{key_index + 1}: HTTP {response.status_code}: {body}")
                continue

            try:
                data = response.json()
            except ValueError:
                errors.append(f"key_{key_index + 1}: non-JSON response")
                continue

            if not isinstance(data, dict):
                errors.append(f"key_{key_index + 1}: unexpected response format")
                continue

            error_text = str(data.get("error", "") or "").strip()
            organic = data.get("organic_results", [])
            if error_text:
                unified = self._to_unified(organic) if isinstance(organic, list) else []
                if unified:
                    logger.warning("SerpApi returned error with partial results: %s", error_text[:300])
                    self.active_key_index = key_index
                    return {"results": unified}
                errors.append(f"key_{key_index + 1}: provider error: {error_text[:500]}")
                continue

            self.active_key_index = key_index
            return {"results": self._to_unified(organic if isinstance(organic, list) else [])}

        raise SerpApiAPIError("All configured SerpApi API keys failed. " + " | ".join(errors))

    @staticmethod
    def _to_unified(raw_results: Any) -> List[Dict[str, Any]]:
        unified: List[Dict[str, Any]] = []
        if not isinstance(raw_results, list):
            return unified

        for position, item in enumerate(raw_results, start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("link", "") or "").strip()
            if not url:
                continue
            title = str(item.get("title", "") or "").strip()
            snippet = str(item.get("snippet", "") or "").strip()
            entry: Dict[str, Any] = {
                "url": url,
                "title": title,
                "content": snippet,
                "raw_content": snippet,
                "score": max(0.0, 1.0 - (position - 1) * 0.05),
            }
            favicon = item.get("favicon")
            if favicon:
                entry["favicon"] = favicon
            date = item.get("date")
            if date:
                entry["date"] = str(date)
            unified.append(entry)

        return unified
