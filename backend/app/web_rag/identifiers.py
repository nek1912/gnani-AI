"""P1-7 identifier-aware search + numeral normalization.

Identifiers (notification/order/circular/GR numbers, RBI references,
section/article numbers, Act/Rule years) are the most precise retrieval
keys in government IR — and the most fragile across scripts. This
module:

- normalize_numerals(): Gujarati + Devanagari digits -> Arabic.
  Applied to EXTRACTION and QUERY inputs only; stored evidence text is
  never rewritten.
- extract_query_identifiers(): labeled instrument IDs (validity
  patterns) plus section/article/Act-year/Rule-year patterns.
- identifier_variants(): bounded (<=3) normalized query forms:
  original, numeral-normalized, roman-substituted (lexicon roman
  lists only). One branch uses the single best form — never 11x.
- identifier_match_score(): exact ID match -> +0.60, near-exact
  (same digit sequence, different separators) -> +0.45, else 0.0.
  Year-only overlap is NOT an identifier match.

All 11 user languages share the single identifier branch; scripts are
handled by normalization, not by branch multiplication.
"""

from __future__ import annotations

import logging
import re

from app.web_rag.validity import find_instrument_mentions

logger = logging.getLogger(__name__)

MAX_VARIANTS = 3
MAX_IDS_PER_QUERY = 5

_GUJARATI_DIGITS = "૦૧૨૩૪૫૬૭૮૯"
_DEVANAGARI_DIGITS = "०१२३४५६७८९"
_ARABIC_DIGITS = "0123456789"

_NUMERAL_TABLE = str.maketrans(
    _GUJARATI_DIGITS + _DEVANAGARI_DIGITS,
    _ARABIC_DIGITS * 2,
)

_NON_ARABIC_DIGIT_RE = re.compile(r"[૦-૯०-९]")

_SECTION_RE = re.compile(r"\b[Ss]ection\s+(\d+[A-Za-z]?)")
_ARTICLE_RE = re.compile(r"\b[Aa]rticle\s+(\d+[A-Za-z]*)")
_ACT_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\s+Act\b")
_ACT_YEAR_PREFIX_RE = re.compile(r"\bAct\,?\s+((?:19|20)\d{2})\b")
_RULES_YEAR_RE = re.compile(r"\b[Rr]ules?,?\s+((?:19|20)\d{2})\b")


def normalize_numerals(text: str) -> str:
    """Map Gujarati/Devanagari digits to Arabic (rest untouched)."""
    return str(text or "").translate(_NUMERAL_TABLE)


def has_non_arabic_numerals(text: str) -> bool:
    """True when native-script digits are present."""
    return bool(_NON_ARABIC_DIGIT_RE.search(str(text or "")))


def extract_query_identifiers(query: str) -> list[str]:
    """Labeled identifiers in a query (deduped, capped).

    Instrument IDs via the conservative validity patterns, plus
    section/article numbers and Act/Rule years. Values are short,
    bounded, and never invented.
    """
    normalized = normalize_numerals(query)
    found: list[str] = []
    seen: set[str] = set()

    def _add(value: str | None) -> None:
        cleaned = (value or "").strip().strip(".,;:()[]\"'")
        if not cleaned or len(cleaned) > 32:
            return
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            found.append(cleaned)

    for identifier in find_instrument_mentions(normalized):
        _add(identifier)

    for match in _SECTION_RE.finditer(normalized):
        _add(f"Section {match.group(1)}")

    for match in _ARTICLE_RE.finditer(normalized):
        _add(f"Article {match.group(1)}")

    for match in _ACT_YEAR_RE.finditer(normalized):
        _add(f"{match.group(1)} Act")

    for match in _ACT_YEAR_PREFIX_RE.finditer(normalized):
        _add(f"{match.group(1)} Act")

    for match in _RULES_YEAR_RE.finditer(normalized):
        _add(f"Rules {match.group(1)}")

    return found[:MAX_IDS_PER_QUERY]


def _roman_substitutions(query: str) -> str:
    """Replace lexicon roman tokens with canonical native terms.

    Longest-match, single pass, lexicon lists only — no transliteration
    engine, no invented mappings.
    """
    try:
        from app.web_rag.lexicon import load_lexicon
    except Exception:
        return query

    pairs: list[tuple[str, str]] = []
    for concept in load_lexicon():
        native = list(concept.get("gu", [])) + list(concept.get("hi", []))
        if not native:
            continue
        canonical = native[0]
        for roman in concept.get("roman", []):
            if roman and len(roman) >= 3:
                pairs.append((roman.lower(), canonical))

    pairs.sort(key=lambda item: len(item[0]), reverse=True)

    lowered = query.lower()
    result = query
    for roman, canonical in pairs:
        pattern = re.compile(r"\b" + re.escape(roman) + r"\b", re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(canonical, result)
        if result != query and lowered != result.lower():
            lowered = result.lower()

    return result


def identifier_variants(query: str) -> list[str]:
    """Bounded normalized query forms (original first, <=3 total)."""
    query = str(query or "")
    variants = [query]

    normalized = normalize_numerals(query)
    if normalized != query:
        variants.append(normalized)

    substituted = _roman_substitutions(normalized)
    if substituted != normalized and substituted not in variants:
        variants.append(substituted)

    return variants[:MAX_VARIANTS]


def _digit_sequence(value: str) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def identifier_match_score(query_ids: list[str], validity: dict | None) -> float:
    """Strong signal for exact/near-exact identifier matches.

    +0.60 exact instrument-ID match (case/separator-insensitive
    whitespace only); +0.45 same digit sequence with different
    separators (42/2024 vs 42-2024); else 0.0. Year-only overlap
    never counts.
    """
    if not query_ids or not isinstance(validity, dict):
        return 0.0

    instrument = str(validity.get("instrument_id") or "").strip()
    if not instrument:
        return 0.0

    instrument_lower = instrument.lower()

    for query_id in query_ids:
        candidate = str(query_id or "").strip().lower()
        if not candidate:
            continue
        if candidate == instrument_lower:
            return 0.60
        query_digits = _digit_sequence(candidate)
        instrument_digits = _digit_sequence(instrument_lower)
        if (
            len(query_digits) >= 4
            and query_digits == instrument_digits
            and candidate != instrument_lower
        ):
            return 0.45

    return 0.0
