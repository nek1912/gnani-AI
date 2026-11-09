"""P0-5 bounded facet-aware retrieval.

Fixed facet template (no LLM planner, no ScenarioPlanner dependency):
    eligibility / documents / procedure / deadline / authority / escalation

Facets are implied by the EXISTING intent classification. Only implied
facets get branches (cap 2 facet branches per request). Facet coverage
is ADVISORY metadata — it never gates, filters, or abstains. The
existing evidence gate remains the sole answer-level gate.
"""

from __future__ import annotations

FACETS = [
    "eligibility",
    "documents",
    "procedure",
    "deadline",
    "authority",
    "escalation",
]

# Existing classifier intent -> implied facets. INFORMATIONAL and
# COMPARISON imply no facet branch (the primary branches cover them).
INTENT_FACETS: dict[str, list[str]] = {
    "ELIGIBILITY": ["eligibility"],
    "DOCUMENT_REQUIREMENTS": ["documents"],
    "APPLICATION": ["procedure"],
    "REGISTRATION": ["procedure"],
    "SERVICE_ACCESS": ["procedure"],
    "STATUS": ["procedure"],
    "DEADLINE": ["deadline"],
    "BENEFIT": ["eligibility"],
    "SUBSIDY_AMOUNT": ["eligibility"],
    "CONTACT": ["authority"],
    "LOCATION": ["authority"],
    "GRIEVANCE": ["escalation", "authority"],
    "INFORMATIONAL": [],
    "COMPARISON": [],
}

# Facet -> augmenting query words. Non-English words below are the
# pre-existing INTENT/lexicon-verified terms only.
FACET_WORDS: dict[str, list[str]] = {
    "eligibility": ["eligibility", "criteria", "પાત્રતા", "पात्रता"],
    "documents": ["documents required", "forms", "દસ્તાવેજ", "दस्तावेज"],
    "procedure": ["how to apply", "process", "portal", "અરજી", "आवेदन"],
    "deadline": ["last date", "deadline", "closing date"],
    "authority": ["office", "department", "helpline", "સંપર્ક", "संपर्क"],
    "escalation": ["complaint", "appeal", "helpline", "ફરિયાદ", "शिकायत"],
}

MAX_FACET_BRANCHES = 2
MAX_FACET_WORDS = 3


def facets_for_intent(intent: str | None) -> list[str]:
    """Implied facets for a classifier intent (possibly empty)."""
    return list(INTENT_FACETS.get((intent or "INFORMATIONAL").upper(), []))


def facet_query_words(facet: str) -> list[str]:
    """Augmenting words for one facet (cap MAX_FACET_WORDS)."""
    return list(FACET_WORDS.get(facet, [])[:MAX_FACET_WORDS])


def _word_hit(word: str, text: str) -> bool:
    return word.lower() in text


def result_facets(
    title: str,
    text: str,
    facets: list[str],
) -> list[str]:
    """Facets a single result supports (any augmenting word matches)."""
    blob = f"{title or ''}\n{(text or '')[:4000]}".lower()
    supported: list[str] = []

    for facet in facets:
        if any(_word_hit(word, blob) for word in FACET_WORDS.get(facet, [])):
            supported.append(facet)

    return supported


def facet_coverage(
    results: list[dict],
    facets: list[str],
    top_n: int = 20,
) -> dict[str, dict]:
    """Advisory per-facet coverage over the top fused results.

    Returns {facet: {"supported": bool, "chunk_ids": [...]}}. A facet
    with no supporting chunk is reported, never enforced.
    """
    coverage: dict[str, dict] = {
        facet: {"supported": False, "chunk_ids": []} for facet in facets
    }

    for result in results[:top_n]:
        if not isinstance(result, dict):
            continue

        title = result.get("web_title") or result.get("title") or ""
        text = result.get("text") or result.get("content") or ""
        supported = result_facets(title, text, facets)

        result_facets_existing = result.get("facets")
        if not isinstance(result_facets_existing, list):
            result["facets"] = supported

        chunk_id = result.get("chunk_id")

        for facet in supported:
            entry = coverage[facet]
            entry["supported"] = True
            if chunk_id and chunk_id not in entry["chunk_ids"]:
                entry["chunk_ids"].append(chunk_id)

    return coverage
