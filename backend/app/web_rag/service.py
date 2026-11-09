"""
Web discovery service.

Architecture:

    Query
      ↓
    Existing QueryClassifier
      ↓
    Jurisdiction resolution
      ↓
    Official-source provider search (Tavily + SerpApi)
      ↓
    Web document cleaning
      ↓
    Structure-aware web chunking
      ↓
    BM25 ranking
      ↓
    Evidence threshold
      ↓
    Optional broader trusted-web search
      ↓
    Final web candidates

This module does NOT generate answers.

IMPORTANT:
The QueryClassifier remains the single source of truth for
query classification.

The classification may either be:
    1. supplied by the caller, or
    2. created internally when no classification is supplied.

This allows /chat → RAGPipeline → WebDiscoveryService to
share the SAME classification without creating another
classifier.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from app.web_rag.bm25_ranker import WebBM25Ranker
from app.web_rag.facets import (
    MAX_FACET_BRANCHES,
    facet_coverage,
    facet_query_words,
    facets_for_intent,
)
from app.web_rag.impersonation import assess_impersonation
from app.web_rag.identifiers import (
    extract_query_identifiers,
    has_non_arabic_numerals,
    identifier_variants,
)
from app.web_rag.status import (
    STATUS_PUBLISHERS,
    is_status_query,
    status_branch_terms,
)
from app.web_rag.firecrawl_client import FirecrawlClient
from app.web_rag.providers import resolve_providers
from app.web_rag.query_classifier import (
    MSCS_ANCHOR_DOMAINS,
    QueryClassification,
    QueryClassifier,
)
from app.web_rag.lexicon import (
    NATIVE_STATE_LANG,
    document_type_terms,
    gujarati_branch_query,
    hindi_branch_query,
    native_branch_query,
)
from app.web_rag.leads import (
    build_lead_branches,
    extract_leads,
    tag_lead_sources,
)
from app.web_rag.clusters import cluster_results
from app.web_rag.expansion import expansion_terms
from app.web_rag.retrieval_scorer import rescore
from app.web_rag.scheme_candidate import (
    identify_scheme_candidate,
    boost_scheme_candidate,
)
from app.web_rag.tavily_client import STATE_PORTALS, TavilyClient
from app.web_rag.validity import extract_validity
from app.web_rag.web_cleaner import (
    WebDocumentCleaner,
)

logger = logging.getLogger(__name__)


_API_KEY_PARAM_RE = re.compile(r"(api_key=)[^&\s'\"]+", re.IGNORECASE)


def _sanitize_provider_error(exc: Exception) -> str:
    """Redact embedded API keys from a provider error before logging.

    SerpApi failures surface the full request URL (including api_key=...)
    via the httpx/respx exception text. Tavily/Firecrawl use headers, but
    this scrub is provider-agnostic. Truncates to 300 chars like before.
    """
    return _API_KEY_PARAM_RE.sub(r"\1[REDACTED]", str(exc))[:300]


OFFICIAL_DOMAINS = [
    "gov.in",
    "nic.in",
    "india.gov.in",
    "digitalindia.gov.in",
    "meity.gov.in",
    "pmfby.gov.in",
    "cooperation.gov.in",
    "cooperatives.gov.in",
    "agricoop.gov.in",
    "agricoop.nic.in",
    "farmer.gov.in",
    "agmarknet.gov.in",
    "enam.gov.in",
    "nafscob.org",
    "ncui.coop",
    "iffco.in",
    "kribhco.net",
    "guj.nic.in",
    "gujaratcooperative.gov.in",
    "cooperation.gujarat.gov.in",
    "maharashtra.gov.in",
    "cooperation.mp.gov.in",
    "nabard.org",
    "rbi.org.in",
    "sidbi.in",
    "mudra.org.in",
    "pmjdy.gov.in",
    "pgportal.gov.in",
    "cpgrams.gov.in",
    "serviceonline.gov.in",
    "irdai.gov.in",
    "mca.gov.in",
    "pib.gov.in",
    "mygov.in",
    "nsdcindia.org",
    "pmkvyofficial.org",
    "pmkvyproject.org",
    "aicte-india.org",
    "npscra.nsdl.co.in",
    "nsdl.co.in",
    "onlineservices.nsdl.com",
    "pfrda.org.in",
    "nsiindia.gov.in",
    "jansuraksha.gov.in",
    "pahal-diksha.gov.in",
    "parivahan.gov.in",
]


TRUSTED_SECONDARY_DOMAINS = [

    "prsindia.org",
    "indiacode.nic.in",
    "sci.gov.in",
    "niti.gov.in",

]


WEB_CHUNK_SIZE = 1500
WEB_CHUNK_OVERLAP = 250

WEB_MAX_CHUNKS_PER_SOURCE = 12


class WebDiscoveryService:

    def __init__(
        self,
        tavily_client: TavilyClient | None = None,
        firecrawl_client: FirecrawlClient | None = None,
        bm25_ranker: WebBM25Ranker | None = None,
        classifier: QueryClassifier | None = None,
        web_cleaner: WebDocumentCleaner | None = None,
    ):

        self.tavily = (
            tavily_client
            if tavily_client is not None
            else TavilyClient()
        )

        self.search_providers = []

        for provider in resolve_providers():

            if isinstance(
                provider,
                TavilyClient,
            ):

                if self.tavily not in self.search_providers:
                    self.search_providers.append(
                        self.tavily
                    )

                continue

            if provider not in self.search_providers:
                self.search_providers.append(
                    provider
                )

        if not self.search_providers:

            self.search_providers.append(
                self.tavily
            )

        if (
            firecrawl_client is not None
            and firecrawl_client not in self.search_providers
        ):
            self.search_providers.append(
                firecrawl_client
            )

        self.firecrawl = (
            firecrawl_client
            if firecrawl_client is not None
            else FirecrawlClient()
        )

        self.bm25 = (
            bm25_ranker
            if bm25_ranker is not None
            else WebBM25Ranker()
        )

        self.classifier = (
            classifier
            if classifier is not None
            else QueryClassifier()
        )

        self.cleaner = (
            web_cleaner
            if web_cleaner is not None
            else WebDocumentCleaner()
        )


    @staticmethod
    def _domain(
        url: str,
    ) -> str:

        try:

            return (
                urlparse(url)
                .netloc
                .lower()
                .split(":")[0]
                .removeprefix("www.")
            )

        except Exception:

            return ""


    @staticmethod
    def _domain_in_set(
        url: str,
        allowed: set[str],
    ) -> bool:
        """Exact-or-suffix domain membership (same semantics as the
        official-URL check, applied to a caller-supplied anchor set)."""
        domain = WebDiscoveryService._domain(url)

        if not domain:
            return False

        for entry in allowed:
            if domain == entry or domain.endswith("." + entry):
                return True

        return False

        try:

            return (
                urlparse(url)
                .netloc
                .lower()
                .split(":")[0]
                .removeprefix("www.")
            )

        except Exception:

            return ""


    @classmethod
    def is_official_url(
        cls,
        url: str,
    ) -> bool:

        domain = cls._domain(
            url
        )

        if not domain:
            return False

        for official in OFFICIAL_DOMAINS:

            if (
                domain == official
                or domain.endswith(
                    "." + official
                )
            ):

                return True

        return False


    @classmethod
    def is_trusted_secondary(
        cls,
        url: str,
    ) -> bool:

        domain = cls._domain(
            url
        )

        if not domain:
            return False

        for trusted in TRUSTED_SECONDARY_DOMAINS:

            if (
                domain == trusted
                or domain.endswith(
                    "." + trusted
                )
            ):

                return True

        return False


    @staticmethod
    def _build_query(
        query: str,
        classification: QueryClassification,
    ) -> str:

        additions = []

        if classification.domain != "general":

            additions.append(
                classification.domain
            )

        if classification.state:

            additions.append(
                classification.state
            )

        district = getattr(
            classification,
            "district",
            None,
        )

        if district:

            additions.append(
                district
            )

        # P2-1: bounded terminology expansion on derived branch queries
        # only. The user query above is never rewritten; applied rules
        # are recorded in discovery metadata.
        try:
            extra_terms, _applied = expansion_terms(query, classification)
            additions.extend(extra_terms)
        except Exception:
            logger.warning(
                "Terminology expansion failed; query unmodified",
                exc_info=True,
            )

        if additions:

            return (
                f"{query} "
                + " ".join(additions)
            )

        return query


    @staticmethod
    def _anchor_domains_for(
        classification: QueryClassification,
    ) -> list[str] | None:
        """Select Stage-1 anchor domains for the jurisdiction-first branch.

        P0-3: anchors come from the mandate map (subject + jurisdiction
        scoped), merged with the state's known portal set and the
        gov.in/nic.in catch-alls. MSCS questions scope to central
        cooperative anchors only — never Gujarat RCS sources. Returns
        None when no jurisdiction-first branch is warranted.
        """
        from app.web_rag.mandate_map import anchors_for_domain

        society_type = getattr(
            classification,
            "society_type",
            None,
        )

        state = classification.state

        if society_type == "mscs":
            return anchors_for_domain(
                classification.domain,
                state,
                society_type=society_type,
                jurisdiction=classification.jurisdiction,
            ) or list(MSCS_ANCHOR_DOMAINS)

        if not (
            classification.jurisdiction == "state"
            and state
        ):
            return None

        merged = anchors_for_domain(
            classification.domain,
            state,
            society_type=society_type,
            jurisdiction=classification.jurisdiction,
        ) or []

        state_key = state.lower().replace(" ", "_")
        portals = STATE_PORTALS.get(state_key)

        if portals:
            merged.extend(portals.get("domains", []))

        merged.extend(["gov.in", "nic.in"])

        seen: set[str] = set()
        unique: list[str] = []

        for domain in merged:
            if domain not in seen:
                seen.add(domain)
                unique.append(domain)

        return unique


    @staticmethod
    def _clean_title(
        text: str,
    ) -> str:

        text = str(
            text or ""
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()


    @staticmethod
    def _make_chunk_id(
        url: str,
        index: int,
    ) -> str:

        digest = hashlib.sha1(
            url.encode(
                "utf-8"
            )
        ).hexdigest()[:12]

        return (
            f"web_{digest}_c{index}"
        )


    def _normalize_results(
        self,
        response: dict,
    ) -> list[dict]:

        normalized = []

        raw_results = response.get(
            "results",
            [],
        )

        if not isinstance(
            raw_results,
            list,
        ):

            return []

        for result_index, item in enumerate(
            raw_results,
            start=1,
        ):

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

            title = self._clean_title(
                item.get(
                    "title",
                    "",
                )
            )

            content = str(
                item.get(
                    "content",
                    "",
                )
                or ""
            )

            raw_content = str(
                item.get(
                    "raw_content",
                    "",
                )
                or ""
            )

            source_text = (
                raw_content
                if raw_content.strip()
                else content
            )

            if not source_text.strip():
                continue

            cleaned_text = (
                self.cleaner.clean(
                    source_text
                )
            )

            if (
                len(cleaned_text.strip()) < 80
                and content.strip()
                and content != raw_content
            ):

                cleaned_text = (
                    self.cleaner.clean(
                        content
                    )
                )

            if not cleaned_text.strip():
                continue

            chunks = self.cleaner.chunk(
                cleaned_text,
                chunk_size=WEB_CHUNK_SIZE,
                overlap=WEB_CHUNK_OVERLAP,
                max_chunks=WEB_MAX_CHUNKS_PER_SOURCE,
            )

            if not chunks:
                continue

            validity = extract_validity(
                f"{title}\n{cleaned_text[:4000]}",
                url=url,
                provider_date=item.get("date"),
            )

            impersonation = assess_impersonation(url, title)

            for chunk_index, chunk in enumerate(
                chunks,
                start=1,
            ):

                chunk_id = (
                    self._make_chunk_id(
                        url,
                        (
                            result_index * 100
                            + chunk_index
                        ),
                    )
                )

                official = (
                    self.is_official_url(
                        url
                    )
                )

                trusted_secondary = (
                    self.is_trusted_secondary(
                        url
                    )
                )

                normalized.append(
                    {
                        "chunk_id": chunk_id,

                        "document_id": url,

                        "title": (
                            title
                            or url
                        ),

                        "file_name": None,

                        "issuer": (
                            "Government / Official Web Source"
                            if official
                            else None
                        ),

                        "section_title": (
                            "Web page"
                        ),

                        "section": (
                            "Web page"
                        ),

                        "section_type": (
                            "web"
                        ),

                        "page": None,

                        "source": "web",

                        "source_type": "url",

                        "source_url": url,

                        "url": url,

                        "text": chunk,

                        "content": chunk,

                        "web_title": title,

                        "tavily_score": float(
                            item.get(
                                "score",
                                0.0,
                            )
                            or 0.0
                        ),

                        "favicon": item.get(
                            "favicon"
                        ),

                        "official": official,

                        "trusted_secondary": (
                            trusted_secondary
                        ),

                        "validity": validity,

                        "impersonation": impersonation,

                        "lead_only": bool(impersonation.get("suspicious")),

                        "retrieval_stage": (
                            "official"
                            if official
                            else "web"
                        ),
                    }
                )

        return normalized


    SERVICE_PATH_INTENTS = {
        "APPLICATION",
        "REGISTRATION",
        "ELIGIBILITY",
        "DOCUMENT_REQUIREMENTS",
        "STATUS",
        "SERVICE_ACCESS",
        "BENEFIT",
        "SUBSIDY_AMOUNT",
        "GRIEVANCE",
        "CONTACT",
        "DEADLINE",
    }

    _SERVICE_PATH_QUERY_REGEXES = [
        re.compile(r"\b(how\s+to\s+(apply|register|enroll|access|log\s*in|file|book|track))\b", re.IGNORECASE),
        re.compile(r"\b(how\s+(can|do|does)\s+((i|anyone|a|an|farmer|student|citizen)\s+)?(apply|register|enroll|access|get|file|book|check))\b", re.IGNORECASE),
        re.compile(r"\b(apply|register|enroll|sign\s*up|log\s*in|login|file\s+a|book\s+an|lodge)\b", re.IGNORECASE),
        re.compile(r"\b(apply\s+for|register\s+for|process\s+to\s+(apply|register))\b", re.IGNORECASE),
        re.compile(r"\b(check\s+(status|balance|progress)|track|status of)\b", re.IGNORECASE),
        re.compile(r"\b(application|registration|enrollment|appointment|complaint)\b", re.IGNORECASE),
        re.compile(r"\b(portal|website|online)\b", re.IGNORECASE),
        re.compile(r"\b(documents required|what documents|requirements|eligibility criteria)\b", re.IGNORECASE),
        re.compile(r"\b(who\s+(is|are)\s+(eligible|registered)|am\s+i\s+eligible)\b", re.IGNORECASE),
    ]

    _SERVICE_PATH_URL_REGEXES = [
        re.compile(r"\b(login|log\s*in)\b", re.IGNORECASE),
        re.compile(r"\b(apply|application|applicant|register|registration|enroll|enrollment)\b", re.IGNORECASE),
        re.compile(r"\b(status|tracking|track|check)\b", re.IGNORECASE),
        re.compile(r"\b(portal)\b", re.IGNORECASE),
        re.compile(r"\b(form|forms)\b", re.IGNORECASE),
        re.compile(r"\b(faq|help|support|contact)\b", re.IGNORECASE),
    ]

    _SERVICE_PATH_TITLE_REGEXES = [
        re.compile(r"\b(how to (apply|register|enroll|log in|check status))\b", re.IGNORECASE),
        re.compile(r"\b(apply online|online application|online registration|registration form|application form)\b", re.IGNORECASE),
        re.compile(r"\b(check status|track status|track application|track your)\b", re.IGNORECASE),
        re.compile(r"\b(login|sign in|sign up|register now)\b", re.IGNORECASE),
    ]

    _CURRENT_QUERY_REGEX = re.compile(
        r"\b(latest|current|now|update|updated|recent|new|202[3-9])\b",
        re.IGNORECASE,
    )

    def _assess_official_evidence(
        self,
        query: str,
        results: list[dict],
        classification: QueryClassification,
    ) -> dict:
        """
        Decide whether Stage-1 official-only results are SUFFICIENT for
        the user's actual query intent, or whether Stage-2 broad web
        discovery should run.

        This is a GENERIC, deterministic assessment. It never tries to
        identify the exact ground-truth source/URL. It only answers:
        "do the retrieved official results give enough evidence that a
        further search stage is unnecessary?".

        It reuses existing classification metadata (intent,
        jurisdiction, state) and requires NO additional API / LLM call.

        Returns a dict of diagnostic metadata used both to make the
        Stage-2 decision and to log reasons (STEP 8).
        """

        official = [
            result
            for result in results
            if result.get(
                "official",
                False,
            )
        ]

        unique_urls = {
            result.get(
                "source_url"
            )
            for result in official
            if result.get(
                "source_url"
            )
        }

        intent = (
            classification.intent
            or "INFORMATIONAL"
        ).upper()

        state = (
            classification.state
            or ""
        ).lower()

        jurisdiction = (
            classification.jurisdiction
            or "central"
        ).lower()

        query_tokens = {
            token
            for token in re.findall(
                r"\b\w+\b",
                query.lower(),
            )
            if len(token) >= 4
        }

        best_overlap = 0.0
        best_official = None

        for result in official:

            text = (
                str(
                    result.get(
                        "title",
                        "",
                    )
                )
                + " "
                + str(
                    result.get(
                        "text",
                        "",
                    )
                )
            ).lower()

            source_tokens = set(
                re.findall(
                    r"\b\w+\b",
                    text,
                )
            )

            overlap = (
                len(
                    query_tokens
                    & source_tokens
                )
                / len(query_tokens)
                if query_tokens
                else 0.0
            )

            if overlap > best_overlap:
                best_overlap = overlap
                best_official = result

        query_needs_service = (
            intent in self.SERVICE_PATH_INTENTS
            or any(
                rx.search(query)
                for rx in self._SERVICE_PATH_QUERY_REGEXES
            )
        )

        stage1_has_service_path = False
        service_path_hits = 0
        for result in official:
            url_text = str(result.get("source_url") or "")
            title_text = str(result.get("title") or "")
            url_hits = sum(
                1
                for rx in self._SERVICE_PATH_URL_REGEXES
                if rx.search(url_text)
            )
            title_hits = sum(
                1
                for rx in self._SERVICE_PATH_TITLE_REGEXES
                if rx.search(title_text)
            )
            hits = url_hits + title_hits
            if url_hits > 0 or title_hits > 0:
                stage1_has_service_path = True
                service_path_hits += hits

        is_current_query = bool(
            self._CURRENT_QUERY_REGEX.search(query)
        )

        stage1_has_recent_signal = False
        if is_current_query:
            for result in official:
                if re.search(
                    r"\b(202[0-9]|20[2-9][0-9])\b",
                    str(result.get("title") or "")
                    + " "
                    + str(result.get("text") or ""),
                ):
                    stage1_has_recent_signal = True
                    break

        is_state_query = (
            jurisdiction == "state"
            and bool(state)
        )

        stage1_matches_jurisdiction = (
            not is_state_query
        )  # central queries are always jurisdiction-agnostic here

        if is_state_query:
            state_needle = state.replace(" ", "")
            for result in official:
                haystack = (
                    str(result.get("source_url") or "")
                    + " "
                    + str(result.get("title") or "")
                ).lower().replace(" ", "")
                if (
                    state_needle in haystack
                    or state in (
                        str(result.get("source_url") or "")
                        + " "
                        + str(result.get("title") or "")
                    ).lower()
                ):
                    stage1_matches_jurisdiction = True
                    break

        stage1_result_count = len(official)
        n_unique = len(unique_urls)

        if n_unique < 1 or best_overlap < 0.15:
            return {
                "sufficient": False,
                "reason": "insufficient_baseline",
                "intent": intent,
                "needs_service_path": query_needs_service,
                "has_service_path": stage1_has_service_path,
                "is_current_query": is_current_query,
                "is_state_query": is_state_query,
                "stage1_result_count": stage1_result_count,
                "n_unique": n_unique,
                "best_overlap": round(best_overlap, 4),
                "stage1_matches_jurisdiction": stage1_matches_jurisdiction,
                "best_official_url": (
                    best_official.get("source_url")
                    if best_official
                    else None
                ),
            }

        multi_source = n_unique >= 2

        if query_needs_service and not stage1_has_service_path:
            return {
                "sufficient": False,
                "reason": "intent_needs_service_path",
                "intent": intent,
                "needs_service_path": True,
                "has_service_path": False,
                "is_current_query": is_current_query,
                "is_state_query": is_state_query,
                "stage1_result_count": stage1_result_count,
                "n_unique": n_unique,
                "best_overlap": round(best_overlap, 4),
                "stage1_matches_jurisdiction": stage1_matches_jurisdiction,
                "best_official_url": (
                    best_official.get("source_url")
                    if best_official
                    else None
                ),
            }

        # A state-specific service query must also have evidence matching
        if is_state_query and not stage1_matches_jurisdiction:
            return {
                "sufficient": False,
                "reason": "jurisdiction_mismatch",
                "intent": intent,
                "needs_service_path": query_needs_service,
                "has_service_path": stage1_has_service_path,
                "is_current_query": is_current_query,
                "is_state_query": True,
                "stage1_result_count": stage1_result_count,
                "n_unique": n_unique,
                "best_overlap": round(best_overlap, 4),
                "stage1_matches_jurisdiction": False,
                "best_official_url": (
                    best_official.get("source_url")
                    if best_official
                    else None
                ),
            }

        if is_current_query and not stage1_has_recent_signal:
            return {
                "sufficient": False,
                "reason": "needs_recent_information",
                "intent": intent,
                "needs_service_path": query_needs_service,
                "has_service_path": stage1_has_service_path,
                "is_current_query": True,
                "is_state_query": is_state_query,
                "stage1_result_count": stage1_result_count,
                "n_unique": n_unique,
                "best_overlap": round(best_overlap, 4),
                "stage1_matches_jurisdiction": stage1_matches_jurisdiction,
                "best_official_url": (
                    best_official.get("source_url")
                    if best_official
                    else None
                ),
            }

        if not query_needs_service and best_overlap >= 0.25:
            return {
                "sufficient": True,
                "reason": "informational_satisfied",
                "intent": intent,
                "needs_service_path": False,
                "has_service_path": stage1_has_service_path,
                "is_current_query": is_current_query,
                "is_state_query": is_state_query,
                "stage1_result_count": stage1_result_count,
                "n_unique": n_unique,
                "best_overlap": round(best_overlap, 4),
                "stage1_matches_jurisdiction": stage1_matches_jurisdiction,
                "best_official_url": (
                    best_official.get("source_url")
                    if best_official
                    else None
                ),
            }

        if (
            multi_source
            and stage1_has_service_path
            and best_overlap >= 0.40
        ):
            return {
                "sufficient": True,
                "reason": "service_path_satisfied",
                "intent": intent,
                "needs_service_path": True,
                "has_service_path": True,
                "is_current_query": is_current_query,
                "is_state_query": is_state_query,
                "stage1_result_count": stage1_result_count,
                "n_unique": n_unique,
                "best_overlap": round(best_overlap, 4),
                "stage1_matches_jurisdiction": stage1_matches_jurisdiction,
                "best_official_url": (
                    best_official.get("source_url")
                    if best_official
                    else None
                ),
            }

        return {
            "sufficient": False,
            "reason": "insufficient_actionable_evidence",
            "intent": intent,
            "needs_service_path": query_needs_service,
            "has_service_path": stage1_has_service_path,
            "is_current_query": is_current_query,
            "is_state_query": is_state_query,
            "stage1_result_count": stage1_result_count,
            "n_unique": n_unique,
            "best_overlap": round(best_overlap, 4),
            "stage1_matches_jurisdiction": stage1_matches_jurisdiction,
            "best_official_url": (
                best_official.get("source_url")
                if best_official
                else None
            ),
        }


    def _search_all(
        self,
        query: str,
        *,
        domain: str | None = None,
        state: str | None = None,
        max_results: int = 20,
        chunks_per_source: int = 3,
        include_domains: list[str] | None = None,
        search_depth: str = "advanced",
        include_raw_content: bool = True,
        only_official: bool = False,
        allow_domains: list[str] | None = None,
    ) -> list[dict]:
        """
        Query every active search provider for ``query`` and merge their
        raw results, de-duplicating by source URL.

        Providers are fanned out concurrently so a slow provider cannot
        delay a healthy one; per-provider results are merged back in
        provider order, so URL deduplication keeps the first provider's
        copy exactly as the previous sequential implementation did.

        ``allow_domains`` (P0-3, optional): mandate-map anchor domains
        that pass the official-only filter alongside OFFICIAL_DOMAINS.
        Provider call parameters are unchanged by this flag.
        """
        seen_urls: set[str] = set()
        merged: list[dict] = []
        providers = list(self.search_providers)
        allow_set = (
            {d.lower() for d in allow_domains}
            if allow_domains
            else set()
        )

        def _query_provider(provider: Any) -> list:
            _t_start = time.monotonic()
            try:

                response = provider.search(
                    query,
                    domain=domain,
                    state=state,
                    max_results=max_results,
                    chunks_per_source=chunks_per_source,
                    include_domains=include_domains,
                    search_depth=search_depth,
                    include_raw_content=include_raw_content,
                )

            except Exception as exc:
                # A single provider failing must not break discovery, but
                # hide neither the reason nor the affected provider.
                # Sanitize first: SerpApi errors embed the full request URL
                # including api_key=..., which must never reach the logs.
                _elapsed_ms = (time.monotonic() - _t_start) * 1000
                _err_text = _sanitize_provider_error(exc)
                _is_timeout = "timeout" in _err_text.lower() or "timed out" in _err_text.lower()
                logger.warning(
                    "Web discovery provider failed: provider=%s timeout=%s elapsed_ms=%.0f error=%s",
                    type(provider).__name__,
                    _is_timeout,
                    _elapsed_ms,
                    _err_text,
                )
                return []

            items = (
                response.get(
                    "results",
                    [],
                )
                if isinstance(
                    response,
                    dict,
                )
                else []
            )
            items = items if isinstance(items, list) else []
            _elapsed_ms = (time.monotonic() - _t_start) * 1000
            if not items:
                # Empty is not an exception (e.g. SerpApi "no results"):
                # log at info so timeout-storms vs genuine empty results
                # are distinguishable in future log triage.
                logger.info(
                    "Web discovery provider empty: provider=%s elapsed_ms=%.0f query=%.80s",
                    type(provider).__name__,
                    _elapsed_ms,
                    query,
                )
            return items

        with ThreadPoolExecutor(max_workers=max(1, len(providers))) as executor:
            per_provider_results = list(executor.map(_query_provider, providers))

        for items in per_provider_results:

            for item in items:

                url = str(
                    item.get(
                        "url",
                        "",
                    )
                ).strip()

                if not url:
                    continue

                if (
                    only_official
                    and not self.is_official_url(url)
                    and not (
                        allow_set
                        and self._domain_in_set(url, allow_set)
                    )
                ):
                    continue

                if url in seen_urls:
                    continue

                seen_urls.add(
                    url
                )

                merged.append(
                    item
                )

        return merged


    # P0-1/P0-4/P0-5: bounded branch specifications. Each branch is a
    # single-provider-fan-out search; branches run concurrently and merge
    # with first-branch-wins exact-URL deduplication (same semantics as
    # the provider merge inside _search_all).
    MAX_BRANCHES = 8

    @staticmethod
    def _pool_has_fresh_instrument(
        results: list[dict],
    ) -> bool:
        """True when the pool already holds a fresh official instrument.

        P1-1 skip condition: lead-following adds no value when a
        non-superseded official instrument is already retrieved. Role
        and validity come from the P0 extractors; nothing is inferred.
        """
        from app.web_rag.mandate_map import document_role
        from app.web_rag.validity import SUPERSEDED

        for result in results:
            if not isinstance(result, dict):
                continue
            if not result.get("official", False):
                continue

            url = result.get("source_url") or result.get("url") or ""
            title = result.get("web_title") or result.get("title") or ""

            if (
                document_role(
                    url,
                    title,
                    True,
                    bool(result.get("trusted_secondary", False)),
                )
                != "instrument"
            ):
                continue

            validity = result.get("validity")
            status = (
                validity.get("supersession_status")
                if isinstance(validity, dict)
                else None
            )

            if (status or "unknown").lower() != SUPERSEDED:
                return True

        return False


    def _search_branches(
        self,
        branches: list[dict],
    ) -> tuple[list[dict], dict[str, int]]:
        """Run branch searches concurrently and merge raw provider items.

        Returns (merged_items, branch_counts). Every merged item is tagged
        with its winning branch name ("branch"). Raises nothing: a failing
        branch contributes zero items (isolation mirrors _search_all).
        """
        specs = branches[: self.MAX_BRANCHES]

        if not specs:
            return [], {}

        if len(specs) == 1:
            only = specs[0]

            try:
                items = self._search_all(
                    only["query"],
                    domain=only.get("domain"),
                    state=only.get("state"),
                    max_results=only.get("max_results", 20),
                    chunks_per_source=only.get("chunks_per_source", 3),
                    include_domains=only.get("include_domains"),
                    search_depth=only.get("search_depth", "advanced"),
                    include_raw_content=only.get("include_raw_content", True),
                    only_official=only.get("only_official", False),
                    allow_domains=only.get("allow_domains"),
                )
            except Exception:
                logger.exception(
                    "Web discovery branch failed: branch=%s",
                    only.get("name", "primary"),
                )
                items = []

            for item in items:
                if isinstance(item, dict):
                    item["branch"] = only.get("name", "primary")

            return items, {only.get("name", "primary"): len(items)}

        def _run_branch(spec: dict) -> tuple[str, list]:
            try:
                items = self._search_all(
                    spec["query"],
                    domain=spec.get("domain"),
                    state=spec.get("state"),
                    max_results=spec.get("max_results", 20),
                    chunks_per_source=spec.get("chunks_per_source", 3),
                    include_domains=spec.get("include_domains"),
                    search_depth=spec.get("search_depth", "advanced"),
                    include_raw_content=spec.get("include_raw_content", True),
                    only_official=spec.get("only_official", False),
                    allow_domains=spec.get("allow_domains"),
                )
            except Exception:
                logger.exception(
                    "Web discovery branch failed: branch=%s",
                    spec.get("name", "primary"),
                )
                items = []

            return spec.get("name", "primary"), items

        with ThreadPoolExecutor(
            max_workers=max(1, len(specs))
        ) as executor:
            per_branch = list(executor.map(_run_branch, specs))

        seen_urls: set[str] = set()
        merged: list[dict] = []
        branch_counts: dict[str, int] = {}

        for name, items in per_branch:
            count = 0

            for item in items:
                if not isinstance(item, dict):
                    continue

                url = str(item.get("url", "")).strip()

                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                item["branch"] = name
                merged.append(item)
                count += 1

            branch_counts[name] = count

        return merged, branch_counts


    def _build_recovery_branches(
        self,
        query: str,
        classification: QueryClassification,
        enriched_query: str,
        recovery: dict,
    ) -> list[dict]:
        """Targeted branches for one bounded recovery round (P1-4).

        One axis per round; at most MAX_RECOVERY_BRANCHES branches.
        Each branch reuses the existing official-only + anchor scoping.
        """
        from app.web_rag.recovery import (
            AUTHORITY_AXIS_TERMS,
            MAX_RECOVERY_BRANCHES,
            VALIDITY_AXIS_TERMS,
        )

        axis = str(recovery.get("axis") or "")
        anchors = self._anchor_domains_for(classification)
        scoped = anchors or OFFICIAL_DOMAINS
        branches: list[dict] = []

        def _branch(name: str, branch_query: str, max_results: int = 10) -> dict:
            return {
                "name": name,
                "query": branch_query,
                "domain": classification.domain,
                "state": classification.state,
                "max_results": max_results,
                "chunks_per_source": 3,
                "include_domains": scoped,
                "search_depth": "advanced",
                "include_raw_content": True,
                "only_official": True,
                "allow_domains": anchors,
            }

        if axis == "jurisdiction":
            # Widen: same query without the assumed state token, central
            # official scope (the classification copy already dropped it).
            widened_parts = [query]
            if classification.domain != "general":
                widened_parts.append(classification.domain)
            district = getattr(classification, "district", None)
            if district:
                widened_parts.append(district)
            branches.append(
                _branch("recovery:jurisdiction", " ".join(widened_parts), 12)
            )

        elif axis == "validity":
            state_l = (classification.state or "").lower()
            doc_language = (
                "gu" if state_l == "gujarat"
                else "hi" if classification.jurisdiction == "central"
                else "en"
            )
            validity_query = (
                f"{enriched_query} "
                + " ".join(VALIDITY_AXIS_TERMS)
                + " "
                + " ".join(document_type_terms(doc_language)[:4])
            )
            branches.append(_branch("recovery:validity", validity_query))

        elif axis == "authority":
            authority_query = (
                f"{enriched_query} "
                + " ".join(AUTHORITY_AXIS_TERMS)
            )
            branches.append(_branch("recovery:authority", authority_query))

        elif axis == "language":
            for language in (recovery.get("languages") or [])[:2]:
                if language == "gujarati":
                    gu_query = gujarati_branch_query(
                        query, classification.state,
                        intent=classification.intent,
                    )
                    if gu_query:
                        branches.append(
                            _branch("recovery:language-gu", gu_query, 8)
                        )
                elif language == "hindi":
                    hi_query = hindi_branch_query(
                        query, classification.domain,
                        intent=classification.intent,
                    )
                    if hi_query:
                        branches.append(
                            _branch("recovery:language-hi", hi_query, 8)
                        )

        elif axis == "facet":
            for facet in (recovery.get("facets") or [])[:2]:
                facet_query = (
                    f"{enriched_query} "
                    + " ".join(facet_query_words(facet))
                )
                branches.append(
                    _branch(f"recovery:facet:{facet}", facet_query, 8)
                )

        return branches[:MAX_RECOVERY_BRANCHES]


    def _build_stage1_branches(
        self,
        query: str,
        classification: QueryClassification,
        enriched_query: str,
        recovery: dict | None = None,
    ) -> list[dict]:
        """Build the bounded Stage-1 branch specifications.

        P0-1: the primary official-only branch (unchanged parameters)
        plus a conditional jurisdiction-first branch scoped to the
        resolved jurisdiction's anchor publishers. P0-4 adds the
        Gujarati/Hindi language branches. P0-5 adds the document-type
        branch and at most MAX_FACET_BRANCHES facet branches for
        implied facets only. Hard cap MAX_BRANCHES, enforced in
        _search_branches (typical 3-4, richer queries up to 7).

        P1-4: with a recovery hint, build ONLY the targeted recovery
        branches (cap MAX_RECOVERY_BRANCHES) instead of the full set.
        """
        if recovery:
            return self._build_recovery_branches(
                query,
                classification,
                enriched_query,
                recovery,
            )

        branches = [
            {
                "name": "primary",
                "query": enriched_query,
                "domain": classification.domain,
                "state": classification.state,
                "max_results": 20,
                "chunks_per_source": 3,
                "include_domains": OFFICIAL_DOMAINS,
                "search_depth": "advanced",
                "include_raw_content": True,
                "only_official": True,
            }
        ]

        anchors = self._anchor_domains_for(
            classification
        )

        if anchors:
            branches.append(
                {
                    "name": "jurisdiction",
                    "query": enriched_query,
                    "domain": classification.domain,
                    "state": classification.state,
                    "max_results": 10,
                    "chunks_per_source": 3,
                    "include_domains": anchors,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                    "only_official": True,
                    "allow_domains": anchors,
                }
            )

        # P0-4: ONE Gujarati branch for Gujarat-jurisdiction queries,
        # built lexicon-first (no blind translation). Merges through the
        # same dedup + RRF as every other branch.
        gu_query = gujarati_branch_query(
            query,
            classification.state,
            intent=classification.intent,
        )

        if (
            gu_query
            and classification.jurisdiction == "state"
            and (classification.state or "").lower() == "gujarat"
        ):
            branches.append(
                {
                    "name": "gujarati",
                    "query": gu_query,
                    "domain": classification.domain,
                    "state": classification.state,
                    "max_results": 10,
                    "chunks_per_source": 3,
                    "include_domains": anchors or OFFICIAL_DOMAINS,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                    "only_official": True,
                    "allow_domains": anchors,
                }
            )

        # P0-4: ONE Hindi branch for central-scheme questions only:
        # truly central jurisdiction, or state merely assumed (not
        # explicit) on a central-scheme domain. Explicit-state queries
        # stay on the Gujarati/English branches.
        hi_query = hindi_branch_query(
            query,
            classification.domain,
            intent=classification.intent,
        )

        if hi_query and (
            classification.jurisdiction == "central"
            or bool(getattr(classification, "assumed_state", False))
        ):
            branches.append(
                {
                    "name": "hindi",
                    "query": hi_query,
                    "domain": classification.domain,
                    "state": classification.state,
                    "max_results": 10,
                    "chunks_per_source": 3,
                    "include_domains": OFFICIAL_DOMAINS,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                    "only_official": True,
                }
            )

        # P2-3: ONE state-keyed native branch (mr/bn/ta) for states with
        # both a portal set and verified lexicon terms. Same official
        # scoping as the jurisdiction branch; never multiplies per
        # language (single branch, lexicon-gated).
        state_key = (classification.state or "").lower().replace(" ", "_")
        native_lang = NATIVE_STATE_LANG.get(state_key)

        if native_lang and classification.jurisdiction == "state":
            portals = STATE_PORTALS.get(state_key, {})
            portal_keywords = portals.get("keywords", [])
            state_word = (
                portal_keywords[1]
                if len(portal_keywords) > 1
                else None
            )
            native_query = native_branch_query(
                query, native_lang, state_word=state_word
            )

            if native_query:
                branches.append(
                    {
                        "name": f"native:{native_lang}",
                        "query": native_query,
                        "domain": classification.domain,
                        "state": classification.state,
                        "max_results": 10,
                        "chunks_per_source": 3,
                        "include_domains": anchors or OFFICIAL_DOMAINS,
                        "search_depth": "advanced",
                        "include_raw_content": True,
                        "only_official": True,
                        "allow_domains": anchors,
                    }
                )

        # P1-7: ONE identifier branch when normalization changes
        # something (native-script numerals, romanized identifiers) or
        # labeled IDs are present. Single branch for all 11 languages —
        # scripts are handled by normalization, never by multiplication.
        identifier_tokens: list[str] = []
        normalized_forms = identifier_variants(query)

        if len(normalized_forms) > 1 or has_non_arabic_numerals(query):
            for form in normalized_forms[1:]:
                for token in form.split():
                    if (
                        token not in enriched_query
                        and token not in identifier_tokens
                    ):
                        identifier_tokens.append(token)

        for identifier in extract_query_identifiers(query):
            if (
                identifier not in enriched_query
                and identifier not in identifier_tokens
            ):
                identifier_tokens.append(identifier)

        if identifier_tokens:
            branches.append(
                {
                    "name": "identifier",
                    "query": (
                        f"{enriched_query} "
                        + " ".join(identifier_tokens[:6])
                    ),
                    "domain": classification.domain,
                    "state": classification.state,
                    "max_results": 8,
                    "chunks_per_source": 3,
                    "include_domains": anchors or OFFICIAL_DOMAINS,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                    "only_official": True,
                    "allow_domains": anchors,
                }
            )

        # P1-8: bounded status-evidence branch for current-status
        # questions. Targets status-bearing publishers (subject anchors
        # + PIB/Sansad dated status evidence). Currency itself comes
        # from P0 validity metadata — never inferred from recency.
        if is_status_query(query, classification.intent):
            status_anchors = list(anchors or [])
            for publisher in STATUS_PUBLISHERS:
                if publisher not in status_anchors:
                    status_anchors.append(publisher)

            branches.append(
                {
                    "name": "status",
                    "query": (
                        f"{enriched_query} "
                        + " ".join(status_branch_terms())
                    ),
                    "domain": classification.domain,
                    "state": classification.state,
                    "max_results": 8,
                    "chunks_per_source": 3,
                    "include_domains": status_anchors or OFFICIAL_DOMAINS,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                    "only_official": True,
                    "allow_domains": status_anchors or None,
                }
            )

        # P0-5: document-type branch (core branch 3) for instrument-
        # seeking queries; EN terms plus verified GU/HI document words
        # for the query's language scope.
        implied_facets = facets_for_intent(classification.intent)

        if implied_facets:
            state_l = (classification.state or "").lower()

            if state_l == "gujarat":
                doc_language = "gu"
            elif classification.jurisdiction == "central":
                doc_language = "hi"
            else:
                doc_language = "en"

            doc_query = (
                f"{enriched_query} "
                + " ".join(document_type_terms(doc_language)[:6])
            )

            branches.append(
                {
                    "name": "doctype",
                    "query": doc_query,
                    "domain": classification.domain,
                    "state": classification.state,
                    "max_results": 10,
                    "chunks_per_source": 3,
                    "include_domains": anchors or OFFICIAL_DOMAINS,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                    "only_official": True,
                    "allow_domains": anchors,
                }
            )

            # P0-5: at most MAX_FACET_BRANCHES facet branches, only for
            # facets implied by the classified intent.
            for facet in implied_facets[:MAX_FACET_BRANCHES]:
                facet_query = (
                    f"{enriched_query} "
                    + " ".join(facet_query_words(facet))
                )

                branches.append(
                    {
                        "name": f"facet:{facet}",
                        "query": facet_query,
                        "domain": classification.domain,
                        "state": classification.state,
                        "max_results": 8,
                        "chunks_per_source": 3,
                        "include_domains": anchors or OFFICIAL_DOMAINS,
                        "search_depth": "advanced",
                        "include_raw_content": True,
                        "only_official": True,
                        "allow_domains": anchors,
                    }
                )

        return branches[: self.MAX_BRANCHES]


    def discover(
        self,
        query: str,
        classification: QueryClassification | None = None,
        as_of_date: str | None = None,
        recovery: dict | None = None,
    ) -> dict:

        query = str(
            query or ""
        ).strip()

        if not query:

            raise ValueError(
                "Web discovery query cannot be empty."
            )


        if classification is None:

            classification = (
                self.classifier.classify(
                    query
                )
            )

        enriched_query = (
            self._build_query(
                query,
                classification,
            )
        )


        # P2-1: record applied terminology rules (original query in
        # "query" is never rewritten; enrichment above is derived).
        try:
            _expansion_terms, applied_expansion = expansion_terms(
                query, classification
            )
        except Exception:
            logger.warning(
                "Terminology expansion record failed",
                exc_info=True,
            )
            applied_expansion = {}


        stage1_branches = (
            self._build_stage1_branches(
                query,
                classification,
                enriched_query,
                recovery,
            )
        )

        official_search_items, branch_counts = (
            self._search_branches(
                stage1_branches
            )
        )

        official_response = {
            "results": official_search_items
        }

        official_chunks = (
            self._normalize_results(
                official_response
            )
        )

        official_ranked = (
            self.bm25.rank(
                query=query,
                results=official_chunks,
                top_k=40,
            )
        )


        evidence_assessment = (
            self._assess_official_evidence(
                query=query,
                results=official_ranked,
                classification=classification,
            )
        )

        official_enough = bool(
            evidence_assessment.get(
                "sufficient",
                False,
            )
        )

        # provider failures / 429 / timeout / empty results must never

        stage2_result_count = 0
        stage2_provider_failures = 0
        stage2_went_empty = False
        stage2_trigger_reason = None

        if official_enough:

            final_results = (
                official_ranked
            )

            discovery_stage = (
                "official"
            )

            fallback_used = False

        else:

            stage2_trigger_reason = (
                evidence_assessment.get(
                    "reason",
                    "insufficient_actionable_evidence",
                )
            )

            try:

                broad_search_items = (
                    self._search_all(
                        enriched_query,
                        domain=classification.domain,
                        state=classification.state,
                        max_results=20,
                        chunks_per_source=3,
                        search_depth="advanced",
                        include_raw_content=True,
                        only_official=False,
                    )
                )

                broad_response = {
                    "results": broad_search_items
                }

                broad_chunks = (
                    self._normalize_results(
                        broad_response
                    )
                )

                existing_urls = {
                    result.get(
                        "source_url"
                    )
                    for result in official_ranked
                }

                fallback_chunks = [
                    result
                    for result in broad_chunks
                    if result.get(
                        "source_url"
                    )
                    not in existing_urls
                ]

                stage2_result_count = len(
                    fallback_chunks
                )

                if not fallback_chunks:

                    stage2_went_empty = True
                    final_results = official_ranked
                    discovery_stage = "official"
                    fallback_used = False

                else:

                    combined = (
                        official_ranked
                        + fallback_chunks
                    )

                    final_results = (
                        self.bm25.rank(
                            query=query,
                            results=combined,
                            top_k=40,
                        )
                    )

                    discovery_stage = (
                        "official_plus_web"
                    )

                    fallback_used = True

            except Exception:

                # Any Stage-2 error must not erase Stage-1 results.
                stage2_provider_failures += 1
                stage2_went_empty = True
                final_results = official_ranked
                discovery_stage = "official"
                fallback_used = False


        # P1-1: bounded lead-following round. Secondary mentions of
        # instrument IDs / portals trigger ONE official-targeted round
        # (max 3 leads). Lead sources are tagged lead_only (never
        # authoritative evidence). Skipped when the pool already holds a
        # fresh official instrument.
        lead_data: dict = {
            "leads_found": 0,
            "leads_followed": 0,
            "lead_chunks": 0,
            "lead_tagged": 0,
            "skipped_has_instrument": False,
        }

        try:
            leads = extract_leads(final_results)
            lead_data["leads_found"] = len(leads)
            lead_data["lead_tagged"] = tag_lead_sources(
                final_results, leads
            )

            if leads and not self._pool_has_fresh_instrument(
                final_results
            ):
                lead_anchors = self._anchor_domains_for(
                    classification
                )

                lead_branches = build_lead_branches(
                    leads,
                    classification,
                    lead_anchors,
                    fallback_domains=OFFICIAL_DOMAINS,
                )

                if lead_branches:
                    lead_items, _lead_counts = self._search_branches(
                        lead_branches
                    )

                    lead_data["leads_followed"] = len(lead_branches)

                    lead_response = {"results": lead_items}
                    lead_chunks = self._normalize_results(
                        lead_response
                    )

                    known_urls = {
                        result.get("source_url")
                        for result in final_results
                    }

                    fresh_lead_chunks = [
                        result
                        for result in lead_chunks
                        if result.get("source_url") not in known_urls
                    ]

                    lead_data["lead_chunks"] = len(fresh_lead_chunks)

                    if fresh_lead_chunks:
                        final_results = self.bm25.rank(
                            query=query,
                            results=final_results + fresh_lead_chunks,
                            top_k=40,
                        )
            else:
                lead_data["skipped_has_instrument"] = bool(leads)

        except Exception:

            logger.exception("Lead-following round failed; pool preserved")


        # P1-2: version/mirror clustering metadata (additive annotation
        # only — nothing is removed or reordered here).
        cluster_data: dict = {"clusters": 0, "mirrored_chunks": 0}

        try:
            cluster_summary = cluster_results(final_results)
            cluster_data = {
                "clusters": len(cluster_summary.get("clusters", {})),
                "mirrored_chunks": cluster_summary.get("mirrored_chunks", 0),
            }
        except Exception:

            logger.exception("Clustering failed; pool preserved")


        final_results = (
            rescore(
                query=query,
                results=final_results,
                classification=classification,
                top_k=20,
                as_of_date=as_of_date,
                expansion_terms=[
                    term
                    for terms in applied_expansion.values()
                    for term in terms
                ],
            )
        )


        # P0-5: advisory facet coverage over the fused results. Reported
        # only — it never gates, filters, or abstains.
        implied_facets = facets_for_intent(classification.intent)

        coverage = facet_coverage(
            final_results,
            implied_facets,
        )


        scheme_candidate_data = None

        if (
            classification
            and getattr(
                classification, "domain", None
            )
            == "schemes"
        ):

            scheme_candidate = (
                identify_scheme_candidate(
                    query=query,
                    results=final_results,
                )
            )

            if scheme_candidate is not None:

                final_results = (
                    boost_scheme_candidate(
                        results=final_results,
                        candidate=scheme_candidate,
                    )
                )

                scheme_candidate_data = {
                    "url": (
                        scheme_candidate.get(
                            "source_url"
                        )
                        or scheme_candidate.get("url")
                    ),
                    "score": (
                        scheme_candidate.get(
                            "scheme_candidate_score"
                        )
                    ),
                    "reasons": (
                        scheme_candidate.get(
                            "scheme_candidate_reasons"
                        )
                    ),
                }

                print(
                    f"\nScheme candidate identified: "
                    f"{scheme_candidate_data['url']}"
                )

                print(
                    f"Scheme candidate score: "
                    f"{scheme_candidate_data['score']}"
                )


        for result in final_results:

            result[
                "query_domain"
            ] = classification.domain

            # P1 audit fix: per-source jurisdiction from the publisher
            # (mandate map) when known — central/institutional publishers
            # are jurisdiction-central with no state; Gujarat publishers
            # carry Gujarat. Unknown publishers fall back to the query
            # classification (previous behavior). Unconditional
            # classification stamping made wrong-state evidence
            # indistinguishable and the gate/recovery jurisdiction checks
            # vacuous for web chunks.
            source_url = (
                result.get("source_url")
                or result.get("url")
                or ""
            )

            publisher_jurisdiction: str | None = None
            publisher_state: str | None = None

            try:
                from app.web_rag.mandate_map import find_org

                org = find_org(source_url)

                if org is not None:
                    org_jurisdiction = str(
                        org.get("jurisdiction", "")
                    ).lower()

                    if org_jurisdiction in ("central", "institutional"):
                        publisher_jurisdiction = "central"
                        publisher_state = None
                    elif org_jurisdiction == "gujarat":
                        publisher_jurisdiction = "state"
                        publisher_state = "Gujarat"
            except Exception:
                logger.warning(
                    "Publisher jurisdiction lookup failed",
                    exc_info=True,
                )

            result[
                "jurisdiction"
            ] = (
                publisher_jurisdiction
                or classification.jurisdiction
            )

            result[
                "state"
            ] = (
                publisher_state
                if publisher_jurisdiction is not None
                else classification.state
            )

            result[
                "district"
            ] = getattr(
                classification,
                "district",
                None,
            )

            result[
                "society_type"
            ] = getattr(
                classification,
                "society_type",
                None,
            )

            result[
                "jurisdiction_source"
            ] = getattr(
                classification,
                "jurisdiction_source",
                "none",
            )

            result[
                "jurisdiction_assumed"
            ] = bool(
                getattr(
                    classification,
                    "assumed_state",
                    False,
                )
            )

            result[
                "classification_confidence"
            ] = classification.confidence

            result[
                "discovery_stage"
            ] = discovery_stage

            result[
                "official_search"
            ] = bool(
                result.get(
                    "official",
                    False,
                )
            )

        return {

            "query": query,

            "search_query": enriched_query,

            "classification": {

                "domain": classification.domain,

                "jurisdiction": (
                    classification.jurisdiction
                ),

                "state": classification.state,

                "district": getattr(
                    classification,
                    "district",
                    None,
                ),

                "society_type": getattr(
                    classification,
                    "society_type",
                    None,
                ),

                "case_year": getattr(
                    classification,
                    "case_year",
                    None,
                ),

                "season": getattr(
                    classification,
                    "season",
                    None,
                ),

                "jurisdiction_source": getattr(
                    classification,
                    "jurisdiction_source",
                    "none",
                ),

                "assumed_state": bool(
                    getattr(
                        classification,
                        "assumed_state",
                        False,
                    )
                ),

                "as_of_date": as_of_date,

                "confidence": (
                    classification.confidence
                ),

                "query_intent": (
                    evidence_assessment.get(
                        "intent",
                        classification.intent,
                    )
                ),
            },

            "discovery_stage": (
                discovery_stage
            ),

            "fallback_used": (
                fallback_used
            ),

            "official_evidence_sufficient": (
                official_enough
            ),

            "discovery_metadata": {
                "branches_run": [
                    branch.get("name", "primary")
                    for branch in stage1_branches
                ],
                "branch_counts": branch_counts,
                "jurisdiction": {
                    "state": classification.state,
                    "district": getattr(
                        classification,
                        "district",
                        None,
                    ),
                    "society_type": getattr(
                        classification,
                        "society_type",
                        None,
                    ),
                    "source": getattr(
                        classification,
                        "jurisdiction_source",
                        "none",
                    ),
                    "assumed": bool(
                        getattr(
                            classification,
                            "assumed_state",
                            False,
                        )
                    ),
                },
                "stage1_result_count": (
                    evidence_assessment.get(
                        "stage1_result_count",
                        0,
                    )
                ),
                "stage1_sufficiency": (
                    "sufficient"
                    if official_enough
                    else "insufficient"
                ),
                "stage1_sufficiency_reason": (
                    evidence_assessment.get(
                        "reason",
                        "unknown",
                    )
                ),
                "query_intent": (
                    evidence_assessment.get(
                        "intent",
                        classification.intent,
                    )
                ),
                "needs_service_path": bool(
                    evidence_assessment.get(
                        "needs_service_path",
                        False,
                    )
                ),
                "has_service_path": bool(
                    evidence_assessment.get(
                        "has_service_path",
                        False,
                    )
                ),
                "is_current_query": bool(
                    evidence_assessment.get(
                        "is_current_query",
                        False,
                    )
                ),
                "is_state_query": bool(
                    evidence_assessment.get(
                        "is_state_query",
                        False,
                    )
                ),
                "stage1_best_overlap": (
                    evidence_assessment.get(
                        "best_overlap",
                        0.0,
                    )
                ),
                "stage1_n_unique": (
                    evidence_assessment.get(
                        "n_unique",
                        0,
                    )
                ),
                "stage1_matches_jurisdiction": bool(
                    evidence_assessment.get(
                        "stage1_matches_jurisdiction",
                        True,
                    )
                ),
                "stage2_triggered": (
                    bool(stage2_trigger_reason)
                ),
                "stage2_trigger_reason": (
                    stage2_trigger_reason
                ),
                "stage2_result_count": (
                    stage2_result_count
                ),
                "stage2_went_empty": (
                    stage2_went_empty
                ),
                "stage2_provider_failures": (
                    stage2_provider_failures
                ),
                "lead_following": lead_data,
                "clustering": cluster_data,
                "terminology_expansion": applied_expansion,
                "recovery_hint": recovery or {},
                "facets_implied": implied_facets,
                "facet_coverage": {
                    facet: {
                        "supported": entry["supported"],
                        "chunk_count": len(entry["chunk_ids"]),
                    }
                    for facet, entry in coverage.items()
                },
            },

            "results": final_results,

            "scheme_candidate": (
                scheme_candidate_data
            ),
        }
