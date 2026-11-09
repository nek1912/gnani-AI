"""P0-4 curated lexicon for bounded Gujarati/Hindi retrieval branches.

Lexicon-first, never blind translation: a language branch is built ONLY
from terms in multilingual_lexicon.json (verified terminology only) plus
the state word. No transliteration dependency, no MT in branch
construction, no generated legal terms.

Branch policy (enforced by the builders, not by callers):
- Gujarati branch: Gujarat-jurisdiction queries with >=1 matched
  concept that has Gujarati terms.
- Hindi branch: central-jurisdiction queries on central-scheme
  subjects with >=1 matched concept that has Hindi terms.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_LEXICON_PATH = Path(__file__).with_name("multilingual_lexicon.json")

MAX_BRANCH_TERMS = 10

GUJARAT_WORD = "ગુજરાત"

# Intents that imply the user seeks an instrument/notice: the branch
# additionally carries Gujarati/Hindi document-type words.
INSTRUMENT_SEEKING_INTENTS = {
    "APPLICATION",
    "REGISTRATION",
    "DOCUMENT_REQUIREMENTS",
    "DEADLINE",
    "STATUS",
    "GRIEVANCE",
    "CONTACT",
}

# Concept ids whose terms are document-type words.
DOC_TYPE_CONCEPTS = {"gr", "circular", "notification", "instrument_number"}

# Query domains for which a central Hindi branch is appropriate.
CENTRAL_HINDI_DOMAINS = {
    "pmfby",
    "schemes",
    "agriculture",
    "finlit",
    "financial_inclusion",
    "cooperative",
    "pacs",
    "pacs_governance",
    "pacs_computerization",
}


@lru_cache(maxsize=1)
def load_lexicon() -> list[dict]:
    """Load lexicon concepts (cached). Returns [] when unavailable."""
    try:
        with open(_LEXICON_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        logger.warning("Multilingual lexicon unavailable at %s", _LEXICON_PATH)
        return []

    concepts = data.get("concepts", [])
    return [c for c in concepts if isinstance(c, dict)]


def all_gu_terms() -> set[str]:
    """Every Gujarati term in the lexicon (for the no-unverified-term test)."""
    terms: set[str] = set()
    for concept in load_lexicon():
        for term in concept.get("gu", []):
            terms.add(term)
    terms.add(GUJARAT_WORD)
    return terms


def all_hi_terms() -> set[str]:
    """Every Hindi term in the lexicon (for the no-unverified-term test)."""
    terms: set[str] = set()
    for concept in load_lexicon():
        for term in concept.get("hi", []):
            terms.add(term)
    return terms


# P2-3: all lexicon languages participate in concept matching.
# Lowercasing-all is behavior-identical to P0: every EN/roman token in
# the lexicon is already lowercase (verified), and native scripts are
# caseless, so no new substring matches are introduced.
MATCH_LANGUAGES = ("en", "roman", "gu", "hi", "mr", "bn", "ta")


def matched_concepts(query: str) -> list[dict]:
    """Concepts whose English, roman, or native terms appear in the query.

    Matching is case-insensitive substring on the lowered query. Order
    follows the lexicon file (curated priority), not match count.
    """
    text = str(query or "").lower()
    matched: list[dict] = []

    for concept in load_lexicon():
        candidates: list[str] = []
        for lang in MATCH_LANGUAGES:
            for term in concept.get(lang, []):
                if term:
                    candidates.append(term.lower())

        if any(term in text for term in candidates):
            matched.append(concept)

    return matched


def gujarati_branch_query(
    english_query: str,
    state: str | None,
    intent: str | None = None,
) -> str | None:
    """Build ONE Gujarati retrieval query, or None when not justified.

    Gujarat-jurisdiction gate is applied by the caller; this builder
    additionally requires >=1 matched concept with Gujarati terms.
    """
    matched = matched_concepts(english_query)

    terms: list[str] = []

    for concept in matched:
        for term in concept.get("gu", []):
            if term not in terms:
                terms.append(term)

            if len(terms) >= MAX_BRANCH_TERMS:
                break
        if len(terms) >= MAX_BRANCH_TERMS:
            break

    if not terms:
        return None

    if (intent or "").upper() in INSTRUMENT_SEEKING_INTENTS:
        for concept in load_lexicon():
            if concept.get("id") not in DOC_TYPE_CONCEPTS:
                continue
            for term in concept.get("gu", []):
                if term not in terms and len(terms) < MAX_BRANCH_TERMS + 4:
                    terms.append(term)

    if state and state.lower() == "gujarat" and GUJARAT_WORD not in terms:
        terms.append(GUJARAT_WORD)

    return " ".join(terms)


def hindi_branch_query(
    english_query: str,
    domain: str | None,
    intent: str | None = None,
) -> str | None:
    """Build ONE Hindi retrieval query for central-scheme questions.

    Returns None for non-central-appropriate domains or when no matched
    concept carries Hindi terms.
    """
    if (domain or "general") not in CENTRAL_HINDI_DOMAINS:
        return None

    matched = matched_concepts(english_query)

    terms: list[str] = []

    for concept in matched:
        for term in concept.get("hi", []):
            if term not in terms:
                terms.append(term)

            if len(terms) >= MAX_BRANCH_TERMS:
                break
        if len(terms) >= MAX_BRANCH_TERMS:
            break

    if not terms:
        return None

    if (intent or "").upper() in INSTRUMENT_SEEKING_INTENTS:
        for concept in load_lexicon():
            if concept.get("id") not in DOC_TYPE_CONCEPTS:
                continue
            for term in concept.get("hi", []):
                if term and term not in terms and len(terms) < MAX_BRANCH_TERMS + 4:
                    terms.append(term)

    return " ".join(terms)


def document_type_terms(language: str) -> list[str]:
    """EN + requested-language document-type words (P0-5 doc-type branch).

    Only lexicon-verified terms; English words are the stable query
    vocabulary already used by the classifier.
    """
    terms = [
        "GR", "government resolution", "circular",
        "notification", "guidelines", "SOP",
    ]

    lang_key = "gu" if language == "gu" else "hi" if language == "hi" else None

    if lang_key:
        for concept in load_lexicon():
            if concept.get("id") in DOC_TYPE_CONCEPTS:
                for term in concept.get(lang_key, []):
                    if term and term not in terms:
                        terms.append(term)

    return terms


# P2-3: state-keyed native languages. Only states with BOTH a portal set
# and verified lexicon terms qualify; all other states fall back to
# English retrieval (documented limitation, never silent).
NATIVE_STATE_LANG: dict[str, str] = {
    "maharashtra": "mr",
    "west_bengal": "bn",
    "tamil_nadu": "ta",
}


def all_native_terms(lang: str) -> set[str]:
    """Every lexicon term for a language (no-unverified-term tests)."""
    terms: set[str] = set()
    for concept in load_lexicon():
        for term in concept.get(lang, []):
            terms.add(term)
    return terms


def native_branch_query(
    query: str,
    lang: str,
    state_word: str | None = None,
) -> str | None:
    """Build ONE native-language retrieval query, or None.

    P2-3 generalized builder for state-keyed languages (mr/bn/ta).
    Lexicon-first like the Gujarati/Hindi builders, but WITHOUT
    document-type augmentation (no verified MR/BN/TA doc-type words
    exist). Fires only on matched concepts with terms in `lang`.
    """
    if lang not in ("mr", "bn", "ta"):
        return None

    matched = matched_concepts(query)

    terms: list[str] = []

    for concept in matched:
        for term in concept.get(lang, []):
            if term not in terms:
                terms.append(term)

            if len(terms) >= MAX_BRANCH_TERMS:
                break
        if len(terms) >= MAX_BRANCH_TERMS:
            break

    if not terms:
        return None

    if state_word and state_word not in terms:
        terms.append(state_word)

    return " ".join(terms)
