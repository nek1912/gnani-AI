"""P1-3 role diversification (MMR-lite): final reorder-only layer.

Problem: the top-K can fill with near-identical chunks from one role /
source family (e.g. eight instrument PDFs from one portal) while
complementary authoritative evidence (implementation guidance, official
FAQ) sits just below.

This layer runs AFTER existing ranking/scoring (BM25 -> rescore -> RRF
-> final rerank) and only REORDERS the final top-K. It never replaces
RRF, never changes scores used by gates (same multiset in, same
multiset out), and never drops evidence.

Greedy selection: repeatedly pick the remaining candidate maximizing
``relevance_norm - max_penalty_vs_selected`` where the penalty fires on
(role, family, domain) overlap with already-selected chunks:
    same domain + same role      -> 0.35
    same domain only             -> 0.10
    same family + same role      -> 0.15
Families: official (tier>=4), trusted (tier==3), general (else).
Authority priority is preserved: the single most relevant chunk is
always selected first (zero penalty on the first pick), and relevance
dominates whenever penalties tie.

Deterministic: relevance ties and penalty ties break by input order.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PENALTY_SAME_DOMAIN_ROLE = 0.35
PENALTY_SAME_DOMAIN = 0.10
PENALTY_SAME_FAMILY_ROLE = 0.15


def _relevance_of(result: dict) -> float:
    for key in ("rerank_score", "gemini_score", "retrieval_quality_score", "bm25_score"):
        try:
            value = result.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _tier_of(result: dict) -> int:
    try:
        return int(result.get("source_tier", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _family_of(result: dict) -> str:
    tier = _tier_of(result)
    if tier >= 4:
        return "official"
    if tier == 3:
        return "trusted"
    return "general"


def _domain_of(result: dict) -> str:
    url = str(result.get("source_url") or result.get("url") or "")
    try:
        from urllib.parse import urlparse

        netloc = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
        return netloc.removeprefix("www.").rstrip(".")
    except Exception:
        return ""


def _role_of(result: dict) -> str:
    return str(result.get("document_role") or "secondary")


def _penalty(candidate: dict, selected: dict) -> float:
    same_domain = _domain_of(candidate) == _domain_of(selected) and bool(
        _domain_of(candidate)
    )
    same_role = _role_of(candidate) == _role_of(selected)
    same_family = _family_of(candidate) == _family_of(selected)

    if same_domain and same_role:
        return PENALTY_SAME_DOMAIN_ROLE
    if same_domain:
        return PENALTY_SAME_DOMAIN
    if same_family and same_role:
        return PENALTY_SAME_FAMILY_ROLE
    return 0.0


def diversify(
    results: list[dict],
    top_k: int | None = None,
) -> list[dict]:
    """Greedy MMR-lite reorder of the final ranked list.

    Preserves input keys; stamps ``mmr_penalty`` (penalty applied at
    selection time, 0.0 for the first pick). Returns at most top_k
    items when top_k is given, else the full reordered list.
    """
    pool = [r for r in (results or []) if isinstance(r, dict)]

    if len(pool) <= 1:
        for item in pool:
            item["mmr_penalty"] = 0.0
        return pool[:top_k] if top_k is not None else pool

    ceiling = max(_relevance_of(r) for r in pool)
    span = ceiling if ceiling > 0 else 1.0

    indexed = list(enumerate(pool))
    selected: list[dict] = []
    remaining = list(indexed)

    while remaining:
        best = None
        best_key = None

        for position, (index, candidate) in enumerate(remaining):
            relevance_norm = _relevance_of(candidate) / span
            penalty = 0.0
            for picked in selected:
                penalty = max(penalty, _penalty(candidate, picked))
            key = (relevance_norm - penalty, -index)
            if best_key is None or key > best_key:
                best_key = key
                best = (position, index, candidate, penalty)

        position, _, candidate, penalty = best
        candidate["mmr_penalty"] = round(penalty, 4)
        selected.append(candidate)
        remaining.pop(position)

    if top_k is not None:
        selected = selected[:top_k]

    return selected
