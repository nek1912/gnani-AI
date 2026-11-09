"""
Search-provider factory for the WebDiscovery layer.

The WebDiscoveryService performs web search through one or more
providers. This module centralises HOW providers are chosen so that
swapping or adding a search engine later requires NO pipeline changes:

  * set ``SEARCH_PROVIDERS`` in the backend .env file to a
    comma-separated list of provider names (e.g. ``tavily,firecrawl``);
  * configure that provider's API key in .env;
  * add a client class + one registration line below.

Every client must expose a uniform ``.search(query, *, max_results,
chunks_per_source, include_domains, exclude_domains, search_depth,
include_raw_content) -> {"results": [...]}`` interface so the service
and its normalizer stay engine-agnostic.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from app.web_rag.firecrawl_client import (
    FirecrawlClient,
)
from app.web_rag.serpapi_client import (
    SerpApiClient,
)
from app.web_rag.tavily_client import (
    TavilyClient,
)


# backend/.env is the single source of truth (see app/config.py). Load it into
# os.environ for the os.getenv readers below (SEARCH_PROVIDERS). It must be
# THIS file: loading the repo-root .env instead pushed its stale
# ALLOWED_ORIGINS into os.environ — where pydantic gives it priority over
# backend/.env — and every cross-origin browser request was rejected.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


DEFAULT_PROVIDERS = "tavily"


def _settings_search_providers() -> str:
    """Settings.search_providers when available, else "".

    Never raises: provider resolution must stay deterministic even when
    Settings cannot be constructed (e.g. minimal test envs).
    """
    try:
        from app.config import get_settings

        return (get_settings().search_providers or "").strip()
    except Exception:
        return ""


_PROVIDER_FACTORIES = {
    "tavily": lambda: TavilyClient(),
    "firecrawl": lambda: FirecrawlClient(),
    "serpapi": lambda: SerpApiClient(),
}


def resolve_providers(
    raw: str | None = None,
) -> list[Any]:
    # Precedence (deterministic, observable via the resolution log):
    # explicit arg > SEARCH_PROVIDERS env > Settings.search_providers
    # (backend/.env) > DEFAULT_PROVIDERS. Settings is the documented
    # source of truth; env overrides it for process-level control.
    source = "explicit"
    if raw is None:
        env_raw = (os.getenv("SEARCH_PROVIDERS", "") or "").strip()
        if env_raw:
            raw = env_raw
            source = "env"
        else:
            settings_raw = _settings_search_providers()
            if settings_raw:
                raw = settings_raw
                source = "settings"
            else:
                raw = ""
                source = "default"

    raw = (raw or "").strip()

    names = (
        [p.strip().lower() for p in raw.split(",") if p.strip()]
        if raw
        else [n for n in DEFAULT_PROVIDERS.split(",") if n]
    )

    providers = []

    for name in names:

        factory = (
            _PROVIDER_FACTORIES.get(
                name,
            )
        )

        if factory is None:

            continue

        client = factory()

        configure = getattr(
            client,
            "is_configured",
            None,
        )

        if (
            configure is not None
            and not configure()
        ):

            continue

        providers.append(
            client
        )

    if not providers:

        logger.warning(
            "web providers requested raw=%r (source=%s) yielded none "
            "(unknown names or missing keys); falling back to TavilyClient",
            raw,
            source,
        )
        providers = [
            TavilyClient(),
        ]

    # Observability: the effective provider set depends on config source +
    # key presence (is_configured filtering), so log it per resolution.
    logger.info(
        "web providers resolved raw=%r source=%s effective=%s",
        raw,
        source,
        [type(p).__name__ for p in providers],
    )
    return providers
