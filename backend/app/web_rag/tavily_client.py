"""
Enhanced Tavily web-search client with domain filtering and query enrichment.

This module is the ONLY place where the application communicates
with Tavily.

Responsibilities:
- Send web-search requests with domain filtering and query enrichment
- Keep Tavily credentials server-side
- Rotate between API keys when one fails
- Return raw search results
- Never generate answers
- Never perform RAG
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, List, Dict, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESULTS = 20
DEFAULT_CHUNKS_PER_SOURCE = 3
MAX_API_KEYS = 2

# ============================================================================
# TRUSTED DOMAIN CONFIGURATION
# ============================================================================

# Official Indian Government domains - HIGHEST PRIORITY
OFFICIAL_GOV_DOMAINS = [
    "india.gov.in",
    "gov.in",
    "nic.in",
    "digitalindia.gov.in",
    "meity.gov.in",
    
    # Cooperative & PACS specific
    "nafscob.org",
    "ncui.coop",
    "iffco.in",
    "kribhco.net",
    "cooperatives.gov.in",
    "cooperation.gov.in",
    
    # State cooperative portals
    "guj.nic.in",
    "gujaratcooperative.gov.in",
    "cooperation.gujarat.gov.in",
    "maharashtra.gov.in",
    "cooperation.mp.gov.in",
    
    # Agriculture & PMFBY
    "pmfby.gov.in",
    "agricoop.nic.in",
    "agricoop.gov.in",
    "farmer.gov.in",
    "agmarknet.gov.in",
    "enam.gov.in",
    
    # Financial inclusion
    "nabard.org",
    "rbi.org.in",
    "sidbi.in",
    "mudra.org.in",
    "pmjdy.gov.in",
    
    # Grievance & services
    "pgportal.gov.in",
    "cpgrams.gov.in",
    "serviceonline.gov.in",
]

# Domains to ALWAYS exclude - noise sources
EXCLUDED_DOMAINS = [
    # Generic content farms
    "medium.com",
    "quora.com",
    "reddit.com",
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    
    # Marketing/coaching spam
    "coachfoundation.com",
    "lifecoachtraining.com",
    "coachingfederation.org",
    "keithwebb.com",
    "paperbell.com",
    
    # Generic how-to sites
    "wikihow.com",
    "ehow.com",
    "about.com",
    "thebalance.com",
    
    # News aggregators
    "news.google.com",
    "flipboard.com",
    
    # E-commerce
    "amazon.com",
    "amazon.in",
    "flipkart.com",
]

# Domain-specific search context
DOMAIN_SEARCH_CONTEXT = {
    "pacs": {
        "keywords": ["PACS", "cooperative society", "sahakari", "primary agricultural credit society", "cooperative bank", "cooperative training"],
        "include_domains": ["nafscob.org", "ncui.coop", "cooperatives.gov.in", "nabard.org", "cooperation.gov.in"],
        "site_filter": "site:gov.in OR site:nabard.org OR site:nafscob.org OR site:ncui.coop",
    },
    "pacs_governance": {
        "keywords": ["PACS", "cooperative society", "byelaws", "sahakari", "primary agricultural credit society", "cooperative bank", "cooperative training"],
        "include_domains": ["nafscob.org", "ncui.coop", "cooperatives.gov.in", "nabard.org", "cooperation.gov.in"],
        "site_filter": "site:gov.in OR site:nabard.org OR site:nafscob.org OR site:ncui.coop",
    },
    "pacs_computerization": {
        "keywords": ["PACS computerization", "digitization", "core banking", "NCIP", "ERP", "PACS project"],
        "include_domains": ["cooperatives.gov.in", "cooperation.gov.in", "nabard.org", "nafscob.org"],
        "site_filter": "site:gov.in OR site:nabard.org OR site:cooperation.gov.in",
    },
    "cooperative": {
        "keywords": ["cooperative", "sahakari", "credit society", "cooperative training"],
        "include_domains": ["nafscob.org", "ncui.coop", "cooperatives.gov.in", "cooperation.gov.in"],
        "site_filter": "site:gov.in OR site:coop OR site:nafscob.org",
    },
    "pmfby": {
        "keywords": ["PMFBY", "Pradhan Mantri Fasal Bima Yojana", "crop insurance", "fasal bima"],
        "include_domains": ["pmfby.gov.in", "agricoop.nic.in", "farmer.gov.in", "agricoop.gov.in"],
        "site_filter": "site:pmfby.gov.in OR site:agricoop.nic.in OR site:gov.in",
    },
    "agriculture": {
        "keywords": ["agriculture", "farming", "kisan", "krishi", "farmer scheme"],
        "include_domains": ["agricoop.nic.in", "farmer.gov.in", "agmarknet.gov.in", "agricoop.gov.in"],
        "site_filter": "site:gov.in agriculture",
    },
    "schemes": {
        "keywords": ["government scheme", "yojana", "subsidy", "benefit", "eligibility"],
        "include_domains": ["india.gov.in", "myscheme.gov.in", "gov.in"],
        "site_filter": "site:gov.in scheme eligibility",
    },
    "financial_inclusion": {
        "keywords": ["financial inclusion", "bank account", "Jan Dhan", "MUDRA", "microfinance"],
        "include_domains": ["pmjdy.gov.in", "mudra.org.in", "rbi.org.in", "nabard.org"],
        "site_filter": "site:gov.in OR site:rbi.org.in OR site:nabard.org",
    },
    "finlit": {
        "keywords": ["financial literacy", "KCC", "Kisan Credit Card", "loan", "banking"],
        "include_domains": ["rbi.org.in", "nabard.org", "pmjdy.gov.in"],
        "site_filter": "site:gov.in OR site:rbi.org.in OR site:nabard.org",
    },
    "grievance": {
        "keywords": ["grievance", "complaint", "RTI", "CPGRAMS", "public grievance"],
        "include_domains": ["pgportal.gov.in", "cpgrams.gov.in"],
        "site_filter": "site:pgportal.gov.in OR site:cpgrams.gov.in",
    },
    "driving_licence": {
        "keywords": ["driving licence", "learner permit", "RTO", "parivahan", "sarathi"],
        "include_domains": ["parivahan.gov.in", "sarathi.parivahan.gov.in"],
        "site_filter": "site:parivahan.gov.in",
    },
}

# State-specific portals
STATE_PORTALS = {
    "gujarat": {
        "domains": ["gujaratindia.gov.in", "guj.nic.in", "digitalgujarat.gov.in", "ikhedut.gujarat.gov.in", "cooperation.gujarat.gov.in"],
        "keywords": ["Gujarat", "ગુજરાત"],
    },
    "maharashtra": {
        "domains": ["maharashtra.gov.in", "aaplesarkar.mahaonline.gov.in"],
        "keywords": ["Maharashtra", "महाराष्ट्र"],
    },
    "madhya_pradesh": {
        "domains": ["mp.gov.in", "mpedistrict.gov.in", "cooperation.mp.gov.in"],
        "keywords": ["Madhya Pradesh", "मध्य प्रदेश"],
    },
    "rajasthan": {
        "domains": ["rajasthan.gov.in", "emitra.rajasthan.gov.in"],
        "keywords": ["Rajasthan", "राजस्थान"],
    },
    "tamil_nadu": {
        "domains": ["tn.gov.in", "tnega.tn.gov.in"],
        "keywords": ["Tamil Nadu", "தமிழ்நாடு"],
    },
    "west_bengal": {
        "domains": ["wb.gov.in", "wbprd.gov.in"],
        "keywords": ["West Bengal", "পশ্চিমবঙ্গ"],
    },
}


class TavilyConfigurationError(RuntimeError):
    """Raised when Tavily is not configured."""


class TavilyAPIError(RuntimeError):
    """Raised when all Tavily API attempts fail."""


class TavilyClient:
    """Enhanced Tavily client with domain filtering and query enrichment."""

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
    def _load_api_keys() -> list[str]:
        settings = get_settings()
        keys = []
        for value in (settings.tavily_api_key_1, settings.tavily_api_key_2):
            if value and value.strip():
                keys.append(value.strip())
        return keys[:MAX_API_KEYS]

    def is_configured(self) -> bool:
        return bool(self.api_keys)

    def require_configuration(self) -> None:
        if not self.api_keys:
            raise TavilyConfigurationError(
                "No Tavily API key is configured. "
                "Set TAVILY_API_KEY_1 and optionally TAVILY_API_KEY_2 in the backend .env file."
            )

    def _build_enriched_query(
        self,
        query: str,
        domain: Optional[str] = None,
        state: Optional[str] = None,
    ) -> str:
        """Enrich search query with domain and state context."""
        enriched_parts = [query]

        if domain and domain in DOMAIN_SEARCH_CONTEXT:
            domain_config = DOMAIN_SEARCH_CONTEXT[domain]
            site_filter = domain_config.get("site_filter", "")
            if site_filter:
                enriched_parts.append(site_filter)
                logger.info(f"Added domain context for '{domain}': {site_filter}")
        else:
            enriched_parts.append("site:gov.in OR site:nic.in official")

        if state and state.lower() in STATE_PORTALS:
            state_config = STATE_PORTALS[state.lower()]
            state_keyword = state_config["keywords"][0]
            enriched_parts.append(state_keyword)
            logger.info(f"Added state context: {state_keyword}")
        elif state:
            enriched_parts.append(state)

        if "india" not in query.lower() and "भारत" not in query:
            enriched_parts.append("India")

        enriched_query = " ".join(filter(None, enriched_parts))
        logger.info(f"Enriched query: '{query}' -> '{enriched_query}'")
        return enriched_query

    def _get_include_domains(self, domain: Optional[str] = None, state: Optional[str] = None) -> List[str]:
        """Get list of domains to prioritize based on query context."""
        include = []
        if domain and domain in DOMAIN_SEARCH_CONTEXT:
            include.extend(DOMAIN_SEARCH_CONTEXT[domain].get("include_domains", []))

        state_key = state.lower() if state else None
        if state_key and state_key in STATE_PORTALS:
            include.extend(STATE_PORTALS[state_key].get("domains", []))

        include.extend(["india.gov.in", "gov.in", "nic.in"])

        seen = set()
        unique = []
        for d in include:
            if d not in seen:
                seen.add(d)
                unique.append(d)
        return unique[:15]

    def _post_filter_results(
        self,
        response: Dict[str, Any],
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Additional filtering of results after Tavily returns them."""
        if not isinstance(response, dict) or "results" not in response:
            return response

        raw_results = response.get("results", [])
        if not isinstance(raw_results, list):
            return response

        original_count = len(raw_results)
        filtered_results = []

        for result in raw_results:
            if not isinstance(result, dict):
                continue
            url = str(result.get("url", "")).lower()
            title = str(result.get("title", "")).lower()
            content = str(result.get("content", "")).lower()

            # Check if URL is from excluded domain
            if any(excluded in url for excluded in EXCLUDED_DOMAINS):
                logger.debug(f"Post-filter excluded: {url}")
                continue

            # Domain-specific relevance check
            if domain and domain in DOMAIN_SEARCH_CONTEXT:
                keywords = DOMAIN_SEARCH_CONTEXT[domain]["keywords"]
                has_keyword = any(
                    kw.lower() in title or kw.lower() in content
                    for kw in keywords
                )
                is_gov = any(g in url for g in [".gov.in", ".nic.in", ".org", ".coop"])
                if not is_gov and not has_keyword:
                    logger.debug(f"Post-filter excluded (no domain keywords): {url}")
                    continue

            filtered_results.append(result)

        response["results"] = filtered_results
        logger.info(f"Post-filter: {original_count} -> {len(filtered_results)} results")
        return response

    def search(
        self,
        query: str,
        *,
        domain: Optional[str] = None,
        state: Optional[str] = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        chunks_per_source: int = DEFAULT_CHUNKS_PER_SOURCE,
        include_domains: Optional[list[str]] = None,
        exclude_domains: Optional[list[str]] = None,
        search_depth: str = "advanced",
        include_raw_content: bool = True,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("Tavily search query cannot be empty.")

        self.require_configuration()

        enriched_query = self._build_enriched_query(query, domain, state)

        if not include_domains:
            include_domains = self._get_include_domains(domain, state)

        merged_exclude = list(set((exclude_domains or []) + EXCLUDED_DOMAINS))

        max_results = max(1, min(int(max_results), 20))
        chunks_per_source = max(1, min(int(chunks_per_source), 3))

        payload = {
            "query": enriched_query,
            "search_depth": search_depth,
            "chunks_per_source": chunks_per_source,
            "max_results": max_results,
            "topic": "general",
            "include_answer": False,
            "include_raw_content": "markdown" if include_raw_content else False,
            "include_images": False,
            "include_image_descriptions": False,
            "include_favicon": True,
            "include_domains": include_domains,
            "exclude_domains": merged_exclude,
            "auto_parameters": False,
            "exact_match": False,
            "include_usage": False,
            "safe_search": False,
        }

        errors = []

        def request_with_key(key_index: int) -> tuple[int, httpx.Response]:
            api_key = self.api_keys[key_index]
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            with httpx.Client(timeout=self.timeout) as client:
                return key_index, client.post(
                    TAVILY_SEARCH_URL,
                    json=payload,
                    headers=headers,
                )

        # Race configured keys so a slow or stale key cannot delay a healthy
        # replacement key and consume the entire WebRAG budget.
        executor = ThreadPoolExecutor(max_workers=len(self.api_keys))
        pending = [
            executor.submit(request_with_key, key_index)
            for key_index in range(len(self.api_keys))
        ]
        try:
            for future in as_completed(pending):
                try:
                    key_index, response = future.result()
                except httpx.RequestError as error:
                    errors.append(f"network error: {error}")
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

                self.active_key_index = key_index
                return self._post_filter_results(data, domain)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        raise TavilyAPIError("All configured Tavily API keys failed. " + " | ".join(errors))
