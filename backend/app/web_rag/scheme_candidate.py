"""
Scheme-specific candidate identification.

This module dynamically identifies the strongest dedicated Scheme
portal from web search results. It operates on results already
retrieved by Tavily/Firecrawl -- it does NOT make additional
provider calls.

DO NOT add scheme-to-URL mappings here.
DO NOT hardcode benchmark URLs.
DO NOT hardcode specific scheme names.

The candidate must be identified purely from generic signals
in the search results.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.web_rag.retrieval_scorer import source_tier, normalize_domain


_CENTRAL_GOV_IN_RE = re.compile(r"^[a-z0-9\-]+\.gov\.in$")
_CENTRAL_NIC_IN_RE = re.compile(r"^[a-z0-9\-]+\.nic\.in$")
_CENTRAL_AUTH_RE = re.compile(r"^[a-z0-9\-]+\.(org\.in|co\.in)$")

_GOV_IN_RE = re.compile(r"\.gov\.in$")


_ANNOUNCEMENT_PATH_HINTS = [
    "press", "pressrelease", "press-release", "pib", "news",
    "announcement", "prid", "note", "factsheet", "media",
    "release", "bulletin",
]

_ANNOUNCEMENT_DOMAIN_HINTS = [
    "pib.gov.in", "mygov.in", "twitter.com", "facebook.com",
]


_PORTAL_URL_HINTS = [
    "apply", "application", "register", "registration",
    "login", "sign-in", "portal", "online", "enroll",
    "enrollment", "submit", "track", "status", "download",
    "form", "services", "service", "dashboard", "home",
]

_PORTAL_TITLE_HINTS = [
    "official portal", "official website", "government portal",
    "scheme portal", "apply online", "register online",
    "official site", "home page", "dashboard",
]


def _domain(url: str) -> str:
    """Extract normalized domain from URL."""
    try:
        netloc = urlparse(url).netloc.lower()
        netloc = netloc.split("@")[-1]
        netloc = netloc.split(":")[0]
        netloc = netloc.removeprefix("www.")
        return netloc.rstrip(".")
    except Exception:
        return ""


def _path(url: str) -> str:
    """Extract lowercased path from URL."""
    try:
        return (urlparse(url).path or "").lower()
    except Exception:
        return ""


def _tokens(text: str) -> set[str]:
    """Extract alphanumeric tokens (3+ chars) from text."""
    return {
        t for t in re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
    }


def score_scheme_candidate(
    url: str,
    title: str,
    text: str,
    query: str,
    official: bool,
    trusted_secondary: bool,
) -> dict:
    """
    Score a single search result as a potential dedicated Scheme
    portal.

    Returns a dict with:
        - score: float (0.0 to ~1.0, higher = better candidate)
        - signals: dict of individual signal scores
        - reasons: list of human-readable reason strings

    This function is PURE and DETERMINISTIC. It makes no API calls
    and uses no external knowledge.
    """

    domain = _domain(url)
    path = _path(url)
    title_lower = (title or "").lower()
    text_lower = (text or "")[:5000].lower()

    q_tokens = _tokens(query)
    domain_tokens = _tokens(domain)
    path_tokens = _tokens(path)
    title_tokens = _tokens(title)

    reasons = []


    url_blob_tokens = domain_tokens | path_tokens
    url_overlap = len(q_tokens & url_blob_tokens)

    if url_overlap == 0:
        url_text = domain + " " + path
        subtitle_hits = sum(
            1 for t in q_tokens if t in url_text
        )
        url_overlap = subtitle_hits

    url_token_score = min(1.0, url_overlap * 0.20)

    if url_overlap > 0:
        reasons.append(f"URL tokens match query: {url_overlap}")


    scheme_path_hints = [
        "scheme", "yojana", "subsidy", "benefit",
        "programme", "program", "portal",
    ]
    path_scheme_hits = sum(1 for h in scheme_path_hints if h in path)
    path_score = min(0.30, path_scheme_hits * 0.10)

    if path_scheme_hits > 0:
        reasons.append(f"URL path contains scheme terms: {path_scheme_hits}")


    title_overlap = len(q_tokens & title_tokens)
    title_score = min(1.0, title_overlap * 0.18)

    if title_overlap > 0:
        reasons.append(f"Title tokens match query: {title_overlap}")


    content_tokens = _tokens(text_lower)
    content_overlap = len(q_tokens & content_tokens)
    content_score = min(0.50, content_overlap / max(len(q_tokens), 1) * 0.40)

    if content_overlap > 0:
        reasons.append(f"Content tokens match query: {content_overlap}")


    official_score = 0.0
    if official:
        official_score = 0.40
        reasons.append("Official government domain")
    elif trusted_secondary:
        official_score = 0.20
        reasons.append("Trusted secondary domain")


    portal_url_hits = sum(1 for h in _PORTAL_URL_HINTS if h in path)
    portal_title_hits = sum(1 for h in _PORTAL_TITLE_HINTS if h in title_lower)
    portal_score = min(0.30, (portal_url_hits + portal_title_hits) * 0.10)

    if portal_url_hits > 0 or portal_title_hits > 0:
        reasons.append(f"Portal indicators: url={portal_url_hits}, title={portal_title_hits}")


    article_penalty = 0.0
    is_announcement = (
        any(h in path for h in _ANNOUNCEMENT_PATH_HINTS)
        or any(h in domain for h in _ANNOUNCEMENT_DOMAIN_HINTS)
    )
    if is_announcement:
        article_penalty = 0.30
        reasons.append("Announcement/press-release page")


    commercial_penalty = 0.0
    commercial_indicators = [
        "wikipedia", "quora", "facebook", "reddit", "blogspot",
        "wordpress", ".blog.", "testbook", "linkedin", "medium.com",
        "bankbazaar", "paisabazaar", "leverageedu", "jagranjosh",
    ]
    if any(h in domain for h in commercial_indicators):
        commercial_penalty = 0.40
        reasons.append("Commercial/non-official domain")


    central_bonus = 0.0
    if _CENTRAL_GOV_IN_RE.match(domain):
        if url_token_score > 0 or title_score > 0.1:
            central_bonus = 0.10
            reasons.append("Central government domain")
    elif _CENTRAL_AUTH_RE.match(domain):
        if url_token_score > 0 or title_score > 0.1:
            central_bonus = 0.05
            reasons.append("Authorized institution domain")


    composite = (
        url_token_score * 0.30
        + path_score
        + title_score * 0.25
        + content_score * 0.10
        + official_score * 0.20
        + portal_score
        + central_bonus
        - article_penalty
        - commercial_penalty
    )

    composite = max(0.0, min(1.0, composite))

    return {
        "score": round(composite, 4),
        "signals": {
            "url_token_score": round(url_token_score, 4),
            "path_score": round(path_score, 4),
            "title_score": round(title_score, 4),
            "content_score": round(content_score, 4),
            "official_score": round(official_score, 4),
            "portal_score": round(portal_score, 4),
            "central_bonus": round(central_bonus, 4),
            "article_penalty": round(article_penalty, 4),
            "commercial_penalty": round(commercial_penalty, 4),
        },
        "reasons": reasons,
    }


def identify_scheme_candidate(
    query: str,
    results: list[dict],
    min_score: float = 0.15,
) -> dict | None:
    """
    From a list of search results, identify the one most likely
    to be a dedicated Scheme portal.

    Returns the best candidate dict with added metadata keys:
        - scheme_candidate: True
        - scheme_candidate_score: float
        - scheme_candidate_reasons: list[str]

    Returns None if no candidate exceeds min_score.

    This function does NOT modify the input results list.
    It returns a COPY of the best candidate with metadata added.
    """

    if not results or not query.strip():
        return None

    best_candidate = None
    best_score = 0.0
    best_meta = None

    for result in results:
        if not isinstance(result, dict):
            continue

        url = (
            result.get("source_url")
            or result.get("url")
            or ""
        )
        title = (
            result.get("web_title")
            or result.get("title")
            or ""
        )
        text = (
            result.get("text")
            or result.get("content")
            or ""
        )
        official = bool(result.get("official", False))
        trusted_secondary = bool(
            result.get("trusted_secondary", False)
        )

        scoring = score_scheme_candidate(
            url=url,
            title=title,
            text=text,
            query=query,
            official=official,
            trusted_secondary=trusted_secondary,
        )

        if scoring["score"] > best_score:
            best_score = scoring["score"]
            best_candidate = result
            best_meta = scoring

    if best_candidate is None or best_score < min_score:
        return None

    candidate = dict(best_candidate)
    candidate["scheme_candidate"] = True
    candidate["scheme_candidate_score"] = best_meta["score"]
    candidate["scheme_candidate_reasons"] = best_meta["reasons"]
    candidate["scheme_candidate_signals"] = best_meta["signals"]

    return candidate


def boost_scheme_candidate(
    results: list[dict],
    candidate: dict,
) -> list[dict]:
    """
    A2: Authority-aware promotion gate.

    Promote the candidate to position 0 ONLY when:

    1. The candidate's authority tier is STRICTLY HIGHER than
       the authority tier of the result currently at position 1
       (index 0).  Same-tier or lower-tier candidates are never
       promoted -- the rescore ranking is preserved.

    2. The candidate does NOT share the same domain as the
       position-1 result (redundant promotion).

    If either condition fails, the existing ranking is preserved.

    Returns a NEW list. The input list is not modified.
    """

    if not results or candidate is None:
        return list(results)

    candidate_url = (
        candidate.get("source_url")
        or candidate.get("url")
        or ""
    )

    candidate_title = (
        candidate.get("web_title")
        or candidate.get("title")
        or ""
    )

    candidate_official = bool(
        candidate.get("official", False)
    )


    first = results[0]
    first_url = (
        first.get("source_url")
        or first.get("url")
        or ""
    )

    first_title = (
        first.get("web_title")
        or first.get("title")
        or ""
    )

    first_official = bool(
        first.get("official", False)
    )

    cand_domain = normalize_domain(candidate_url)
    first_domain = normalize_domain(first_url)
    if cand_domain == first_domain:
        return list(results)

    cand_tier, _ = source_tier(
        candidate_url, candidate_title, candidate_official, False
    )
    first_tier, _ = source_tier(
        first_url, first_title, first_official, False
    )

    if cand_tier <= first_tier:
        return list(results)


    filtered = []
    found = False
    for result in results:
        result_url = (
            result.get("source_url")
            or result.get("url")
            or ""
        )
        if result_url == candidate_url and not found:
            found = True
            continue
        filtered.append(result)

    return [candidate] + filtered
