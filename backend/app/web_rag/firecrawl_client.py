"""
Firecrawl web-search client.

This module is the ONLY place where the application communicates
with Firecrawl.

It mirrors the TavilyClient interface so the WebDiscoveryService can
treat both search engines identically behind a single, swappable
provider abstraction. To swap or add a search engine later, implement
a client with the same ``.search(...)`` signature and register it in
the provider factory (see ``web_discovery/providers.py``).

Responsibilities:
- Send web-search requests
- Keep Firecrawl credentials server-side
- Return raw search results in the unified shape:
      {"results": [ {url, title, content, raw_content?}, ... ]}
- Never generate answers
- Never perform RAG
"""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv
from pathlib import Path


# backend/.env is the single source of truth — see the note in
# web_rag/providers.py. Loading the repo-root .env here pushed its stale
# ALLOWED_ORIGINS into os.environ and overrode the correct file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


FIRECRAWL_SEARCH_URL = (
    "https://api.firecrawl.dev/v1/search"
)

DEFAULT_TIMEOUT_SECONDS = 10

DEFAULT_MAX_RESULTS = 20


class FirecrawlConfigurationError(
    RuntimeError
):
    """Raised when Firecrawl is not configured."""


class FirecrawlAPIError(
    RuntimeError
):
    """Raised when the Firecrawl request fails."""


class FirecrawlClient:

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):

        self.api_key = (
            api_key
            or os.getenv(
                "FIRECRAWL_API_KEY",
                "",
            )
        )

        self.api_key = (
            self.api_key.strip()
            if self.api_key
            else ""
        )

        self.api_url = (
            api_url
            or os.getenv(
                "FIRECRAWL_API_URL",
                "",
            )
        )

        self.api_url = (
            self.api_url.strip()
            if self.api_url
            else FIRECRAWL_SEARCH_URL
        )

        self.timeout = timeout


    def is_configured(self) -> bool:

        return bool(
            self.api_key
        )


    def require_configuration(self) -> None:

        if not self.api_key:

            raise FirecrawlConfigurationError(
                "No Firecrawl API key is configured. "
                "Set FIRECRAWL_API_KEY in the backend .env file."
            )


    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        state: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        chunks_per_source: int = 3,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        search_depth: str = "advanced",
        include_raw_content: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:

        query = query.strip()

        if not query:

            raise ValueError(
                "Firecrawl search query cannot be empty."
            )

        self.require_configuration()

        max_results = max(
            1,
            min(
                int(max_results),
                DEFAULT_MAX_RESULTS,
            ),
        )


        payload: dict[str, Any] = {

            "query": query,

            "limit": max_results,

            "lang": "en",
        }

        if include_domains:

            payload["origin"] = (
                "https://" + (" ".join(str(d).lstrip("/") for d in include_domains))
            )

        try:

            response = requests.post(
                self.api_url,
                json=payload,
                headers={
                    "Authorization": (
                        f"Bearer {self.api_key}"
                    ),
                    "Content-Type": (
                        "application/json"
                    ),
                },
                timeout=self.timeout,
            )

        except requests.RequestException as error:

            raise FirecrawlAPIError(
                f"Firecrawl network error: {error}"
            ) from error

        if response.status_code == 429:

            raise FirecrawlAPIError(
                "Firecrawl rate limit exceeded (HTTP 429). "
                "The free tier allows roughly 10 requests/minute."
            )

        if not response.ok:

            body = response.text[
                :1000
            ]

            raise FirecrawlAPIError(
                f"Firecrawl HTTP {response.status_code}: "
                f"{body}"
            )

        try:

            data = response.json()

        except ValueError as error:

            raise FirecrawlAPIError(
                "Firecrawl non-JSON response"
            ) from error

        raw_results = (
            data.get(
                "data",
                [],
            )
            if isinstance(
                data,
                dict,
            )
            else []
        )

        unified_results = (
            self._to_unified(raw_results)
        )

        return {
            "results": unified_results
        }


    @staticmethod
    def _to_unified(
        raw_results: list,
    ) -> list[dict]:

        unified = []

        for item in raw_results:

            if not isinstance(
                item,
                dict,
            ):

                continue

            url = str(
                item.get(
                    "url",
                    "",
                )
            ).strip()

            if not url:

                continue

            description = str(
                item.get(
                    "description",
                    "",
                )
                or ""
            ).strip()

            markdown = str(
                item.get(
                    "markdown",
                    "",
                )
                or ""
            ).strip()

            unified.append(
                {
                    "url": url,
                    "title": str(
                        item.get(
                            "title",
                            "",
                        )
                        or ""
                    ).strip(),
                    "content": (
                        markdown
                        if markdown
                        else description
                    ),
                    "raw_content": (
                        markdown
                        if markdown
                        else ""
                    ),
                }
            )

        return unified
