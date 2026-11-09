"""Post-generation answer grounding verification.

Two-layer check:
1. Regex extraction (fast) — extracts numbers, dates, named entities,
   conditions, and geographic-scope claims (closed state gazetteer +
   closed exclusivity/universality marker sets; no similarity thresholds)
2. LLM verification (for complex cases) — triggered when Layer 1 finds issues

Citation binding: claims in a sentence carrying explicit [chunk:ID]
citation(s) are checked ONLY against the cited chunk(s). Uncited
evidence never rescues a cited claim. Multi-citation sentences use the
union of their cited chunks. Sentences without citations keep the legacy
whole-pool check. Citation-ID validity itself stays with the citation
verifier; grounding decides claim SUPPORT.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from typing import Any

from app.citation_verifier import normalize_citation_markers
from app.contracts import EvidenceChunk

logger = logging.getLogger(__name__)


@dataclass
class UnsupportedClaim:
    """A claim in the answer that cannot be grounded in evidence."""
    claim_text: str
    claim_type: str  # "number", "date", "entity", "condition", "geography"
    evidence_chunk_ids: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class GroundingResult:
    """Result of post-generation grounding verification."""
    has_unsupported_claims: bool = False
    unsupported_claims: list[UnsupportedClaim] = field(default_factory=list)
    all_claims: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns for fact extraction
# ---------------------------------------------------------------------------

# Numbers: integers, decimals, percentages, currency
# Requires either a % suffix or a currency prefix to avoid extracting
# bare numbers that are parts of dates (e.g., "31" in "31 March 2025").
_NUMBER_PATTERN = re.compile(
    r'(?:₹|Rs\.?|INR)\s*\d+(?:\.\d+)?(?:\s*(?:lakh|crore|million|billion))?'
    r'|\d+(?:\.\d+)?%'
    r'|\d+(?:\.\d+)?\s*(?:lakh|crore|million|billion)'
)

# Dates: DD Month YYYY, Month YYYY, DD/MM/YYYY, YYYY-MM-DD
_DATE_PATTERN = re.compile(
    r'\b(?:\d{1,2}[\s/-])?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|'
    r'May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)[\s/-]?\d{0,4}\b',
    re.IGNORECASE,
)
_DATE_PATTERN_ALT = re.compile(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b')
_DATE_PATTERN_ISO = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')

# Named entities: PMFBY, PACS, scheme names, authorities. Scheme names are
# checked as entities so a cited claim naming one scheme cannot be rescued
# by evidence text that only names a different scheme (PMFBY ≠ RWBCIS/WBCIS/
# UPIS/NAIS; PM-KISAN ≠ PMFBY).
_ENTITY_PATTERN = re.compile(
    r'\b(?:PMFBY|RWBCIS|WBCIS|UPIS|NAIS|PM-KISAN|PMKISAN|PACS|CSC|BDO|DM|SDM|DEO|DRDA|NABARD|SECC|NSFI|RBI|IRDAI|'
    r'District Magistrate|Block Development Officer|Sub-Divisional Magistrate|'
    r'District Level Evaluation Committee|State Level Evaluation Committee|'
    r'Ministry of Cooperation|Ministry of Agriculture)\b',
    re.IGNORECASE,
)

# Eligibility conditions
_CONDITION_PATTERN = re.compile(
    r'\b(?:age\s+\d+[-–]\d+\s+years?|minimum\s+\d+|maximum\s+\d+|'
    r'must be|shall be|required to be|should be)\b',
    re.IGNORECASE,
)


def _extract_numbers(text: str) -> list[str]:
    """Extract all numbers from text."""
    return _NUMBER_PATTERN.findall(text)


def _extract_dates(text: str) -> list[str]:
    """Extract all dates from text.

    The month-name pattern also matches bare words (e.g. the modal verb
    "may" matches month "May" case-insensitively). A bare month word with
    no digits is not a verifiable factual claim, so only matches
    containing at least one digit are kept. Real dates ("15 April 2025",
    "31 March") always contain digits and are unaffected.
    """
    dates = _DATE_PATTERN.findall(text)
    dates.extend(_DATE_PATTERN_ALT.findall(text))
    dates.extend(_DATE_PATTERN_ISO.findall(text))
    return [
        d.strip()
        for d in dates
        if d.strip() and any(ch.isdigit() for ch in d)
    ]


def _extract_entities(text: str) -> list[str]:
    """Extract named entities from text."""
    return _ENTITY_PATTERN.findall(text)


def _extract_conditions(text: str) -> list[str]:
    """Extract eligibility conditions from text."""
    return _CONDITION_PATTERN.findall(text)


# ---------------------------------------------------------------------------
# Geographic-scope claims (deterministic, closed vocabularies only)
# ---------------------------------------------------------------------------
#
# Scope: explicit geographic-scope assertions only. The state list reuses the
# canonical English state names from STATE_KEYWORDS in
# app/web_rag/query_classifier.py (kept local so this module does not pull
# in the web_rag package); city/portal aliases (Ahmedabad, ikhedut, ...)
# are intentionally NOT covered. Marker sets are closed function-word lists.
# There is deliberately no open-vocabulary noun/topic check, no overlap or
# similarity threshold, and no paraphrase judgement here.
#
# Support rule per answer sentence mentioning a canonical state S:
# - S named in evidence:
#     - exclusive marker ("only ..." S) passes only when evidence names S
#       alone with no national scope; evidence naming additional states
#       (or national scope) contradicts the exclusivity -> unsupported.
#     - otherwise (inclusive or universal wording) passes: the state itself
#       is supported and bare quantifiers are not judged here.
# - S absent from evidence:
#     - evidence names other explicit state(s) -> unsupported (scope mismatch).
#     - evidence is generic/national:
#         - exclusive or universal marker in the same sentence -> unsupported.
#         - plain inclusive mention ("available in Gujarat") passes, so
#           legitimate state personalization against central/national
#           evidence is never flagged.

_CANONICAL_STATES = (
    "Gujarat",
    "Maharashtra",
    "Madhya Pradesh",
    "Rajasthan",
    "Tamil Nadu",
    "West Bengal",
    "Karnataka",
    "Andhra Pradesh",
    "Uttar Pradesh",
    "Bihar",
    "Odisha",
    "Punjab",
    "Arunachal Pradesh",
    "Assam",
    "Chhattisgarh",
    "Goa",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Kerala",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Sikkim",
    "Telangana",
    "Tripura",
    "Uttarakhand",
)

# National-scope cues in evidence. Mirrors NATIONAL_CUES in
# app/web_rag/query_classifier.py plus inflected forms ("nationally",
# "nationwide") that word-boundary matching on "national" would miss.
_NATIONAL_PATTERN = re.compile(
    r"\b(?:national|nationally|nationwide|all india|all-india|"
    r"pan-india|pan india|countrywide|india|indian|"
    r"central government|entire country)\b",
    re.IGNORECASE,
)

_EXCLUSIVITY_PATTERN = re.compile(
    r"\b(?:only|solely|exclusively)\b|limited to|restricted to|confined to",
    re.IGNORECASE,
)

_UNIVERSAL_PATTERN = re.compile(
    r"\b(?:all|every|each|everyone|everybody)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


def _find_state_mentions(text: str) -> list[tuple[str, str]]:
    """Find canonical-state mentions, preserving answer-case substrings.

    Returns (matched_text, canonical_name) pairs. Single-word names use
    word boundaries so "Goa" never matches "goat" and "Gujarat" never
    matches the language adjective "Gujarati"; multi-word names use
    substring matching (same semantics as the query classifier).
    """
    lowered = text.lower()
    found: list[tuple[str, str]] = []
    for name in _CANONICAL_STATES:
        key = name.lower()
        if " " in key:
            idx = lowered.find(key)
            if idx != -1:
                found.append((text[idx:idx + len(key)], name))
        else:
            match = re.search(r"\b" + re.escape(key) + r"\b", lowered)
            if match is not None:
                found.append((text[match.start():match.end()], name))
    return found


def _check_geography_for_sentence(
    sentence: str,
    evidence_text: str,
    evidence_chunk_ids: list[str],
    seen: set[tuple[str, str]],
) -> list[UnsupportedClaim]:
    """Flag geographically-scoped claims in one sentence.

    Same support rule as :func:`_check_geography`, but evaluated against
    the caller-supplied evidence text (the sentence's cited chunks, or the
    whole pool for uncited sentences).
    """
    evidence_states = {
        canon for _, canon in _find_state_mentions(evidence_text)
    }
    evidence_national = _NATIONAL_PATTERN.search(evidence_text) is not None

    unsupported: list[UnsupportedClaim] = []
    mentions = _find_state_mentions(sentence)
    if not mentions:
        return []
    exclusive = _EXCLUSIVITY_PATTERN.search(sentence) is not None
    universal = _UNIVERSAL_PATTERN.search(sentence) is not None
    for matched_text, canonical in mentions:
        key = (canonical, matched_text.lower())
        if key in seen:
            continue
        if canonical in evidence_states:
            if exclusive and (
                evidence_states != {canonical} or evidence_national
            ):
                seen.add(key)
                unsupported.append(UnsupportedClaim(
                    claim_text=matched_text,
                    claim_type="geography",
                    evidence_chunk_ids=evidence_chunk_ids,
                    reason=(
                        f"Exclusive geographic claim '{matched_text}' is "
                        "contradicted by evidence scope"
                    ),
                ))
            continue
        if evidence_states:
            seen.add(key)
            unsupported.append(UnsupportedClaim(
                claim_text=matched_text,
                claim_type="geography",
                evidence_chunk_ids=evidence_chunk_ids,
                reason=(
                    f"State '{matched_text}' not found in evidence "
                    f"(evidence names: {sorted(evidence_states)})"
                ),
            ))
        elif exclusive or universal:
            seen.add(key)
            unsupported.append(UnsupportedClaim(
                claim_text=matched_text,
                claim_type="geography",
                evidence_chunk_ids=evidence_chunk_ids,
                reason=(
                    f"Geographic-scope claim '{matched_text}' has no "
                    "support in evidence"
                ),
            ))
        # Else: plain inclusive mention against generic/national
        # evidence (legitimate personalization) — supported.
    return unsupported


def _check_geography(
    answer: str,
    evidence_text: str,
    evidence_chunk_ids: list[str],
) -> list[UnsupportedClaim]:
    """Flag geographically-scoped claims with no evidence support."""
    if not answer.strip():
        return []
    unsupported: list[UnsupportedClaim] = []
    seen: set[tuple[str, str]] = set()
    for sentence in _SENTENCE_SPLIT_PATTERN.split(answer):
        unsupported.extend(
            _check_geography_for_sentence(
                sentence, evidence_text, evidence_chunk_ids, seen,
            )
        )
    return unsupported


def _build_evidence_text(chunks: list[EvidenceChunk]) -> str:
    """Concatenate all chunk content for searching."""
    return " ".join(chunk.content for chunk in chunks)


def _check_claims(
    answer: str,
    evidence_text: str,
    extractor: Callable[[str], list[str]],
    claim_type: str,
    evidence_chunk_ids: list[str],
    case_sensitive: bool = True,
) -> list[UnsupportedClaim]:
    """Extract claims and flag those not found in evidence text.

    Args:
        answer: The generated answer text.
        evidence_text: Concatenated evidence content.
        extractor: Function that extracts claims from text.
        claim_type: Type label for unsupported claims (e.g., "number", "date").
        evidence_chunk_ids: Chunk IDs to attach to unsupported claims.
        case_sensitive: Whether the presence check is case-sensitive.

    Returns:
        List of UnsupportedClaim for any extracted claim missing from evidence.
    """
    claims = extractor(answer)
    unsupported: list[UnsupportedClaim] = []
    for claim in claims:
        claim_stripped = claim.strip()
        if not claim_stripped:
            continue
        if claim_type == "number":
            # Boundary-aware match: a shorter number embedded in a longer
            # one (e.g. "2%" inside evidence "12%") is NOT support.
            # Plain `in` substring made such claims verify clean.
            found = re.search(
                r"(?<!\d|\.)" + re.escape(claim_stripped) + r"(?!\d)",
                evidence_text,
            ) is not None
        elif case_sensitive:
            found = claim_stripped in evidence_text
        else:
            found = claim_stripped.lower() in evidence_text.lower()
        if not found:
            unsupported.append(UnsupportedClaim(
                claim_text=claim_stripped,
                claim_type=claim_type,
                evidence_chunk_ids=evidence_chunk_ids,
                reason=f"{claim_type.capitalize()} '{claim_stripped}' not found in evidence",
            ))
    return unsupported


_VERIFICATION_SYSTEM_PROMPT = """You are a fact-verification assistant. Your ONLY job is to verify
whether factual claims are supported by the provided evidence chunks.

RULES:
1. For each claim, respond with ONLY "SUPPORTED" or "UNSUPPORTED"
2. If UNSUPPORTED, provide a one-line reason
3. Do NOT add any other information
4. Do NOT use general knowledge — only the provided evidence matters
5. Be strict: if the claim adds ANY information not in the evidence, it is UNSUPPORTED

Format your response as:
CLAIM 1: [SUPPORTED/UNSUPPORTED] [reason if unsupported]
CLAIM 2: [SUPPORTED/UNSUPPORTED] [reason if unsupported]
...
"""


def _build_verification_prompt(
    claims: list[UnsupportedClaim],
    evidence_chunks: list[EvidenceChunk],
) -> str:
    """Build prompt for LLM verification of unsupported claims."""
    evidence_text = "\n\n".join(
        f"[CHUNK {i+1}] {chunk.content}"
        for i, chunk in enumerate(evidence_chunks[:5])
    )

    claims_text = "\n".join(
        f"CLAIM {i+1}: {c.claim_text} (type: {c.claim_type})"
        for i, c in enumerate(claims)
    )

    return (
        f"== EVIDENCE ==\n{evidence_text}\n\n"
        f"== CLAIMS TO VERIFY ==\n{claims_text}\n\n"
        f"Verify each claim against the evidence. Respond with SUPPORTED or UNSUPPORTED."
    )


def _parse_verification_response(response: str, claims: list[UnsupportedClaim]) -> list[UnsupportedClaim]:
    """Parse LLM verification response and return still-unsupported claims."""
    unsupported: list[UnsupportedClaim] = []
    lines = response.strip().split("\n")

    for i, line in enumerate(lines):
        if i >= len(claims):
            break
        if "UNSUPPORTED" in line.upper():
            unsupported.append(claims[i])

    return unsupported


def verify_with_llm(
    unsupported_claims: list[UnsupportedClaim],
    evidence_chunks: list[EvidenceChunk],
    settings: Any = None,
) -> list[UnsupportedClaim]:
    """Layer 2: LLM verification for complex cases.

    Only called when Layer 1 regex finds issues.
    Returns claims that are still unsupported after LLM verification.
    """
    if not unsupported_claims or not evidence_chunks:
        return unsupported_claims

    try:
        from app.config import get_settings
        from app.providers.groq_llm import GroqLLMProvider
        from app.providers.gemini_llm import GeminiLLMProvider
        from app.llm_fallback import grounded_answer

        settings = settings or get_settings()

        primary_provider = GroqLLMProvider(settings)
        fallback_provider = GeminiLLMProvider(settings)

        user_prompt = _build_verification_prompt(unsupported_claims, evidence_chunks)
        response = grounded_answer(
            primary_provider,
            fallback_provider,
            _VERIFICATION_SYSTEM_PROMPT,
            user_prompt,
        )

        return _parse_verification_response(response, unsupported_claims)

    except Exception as e:
        logger.warning("LLM verification failed, keeping regex results: %s", e)
        return unsupported_claims


# ---------------------------------------------------------------------------
# Citation-to-evidence binding (deterministic, no semantic machinery)
# ---------------------------------------------------------------------------
#
# A [chunk:ID] marker cites retrieved evidence by ID prefix: the 8-char
# prefix for UUID-style chunk IDs, the full ID for web-style IDs
# (mirrors short_citation_id / extract_citations_from_answer in the
# citation verifier). Grounding resolves each sentence's markers to the
# cited chunks and checks that sentence's claims ONLY against cited text.
# Sentences without markers keep the legacy whole-pool check so
# citation-free answers and trailing single citations do not regress.
# A marker that resolves to no chunk leaves the sentence with empty
# evidence (fail closed); citation-ID validity itself stays with the
# citation verifier, which runs before grounding.

_CITATION_MARKER_PATTERN = re.compile(r"\[chunk:([^\]]*)\]")

# A leading run of citation markers inside a split segment trails the
# PREVIOUS sentence (the codebase's trailing-citation convention:
# "claim. [chunk:ID]"). Without re-attachment, a naive terminator split
# detaches markers into their own segment and claims lose their citation.
_LEADING_MARKER_RUN = re.compile(r"^((?:\s*\[chunk:[^\]]*\])+)([\s\S]*)$")


def _split_into_cited_units(answer: str) -> list[str]:
    """Split an answer into sentence units with citations attached.

    Citation-only segments and leading marker runs are merged backward
    onto the preceding unit. A marker with no preceding unit (answer
    starts with a citation) stays with its own segment.
    """
    units: list[str] = []
    for segment in _SENTENCE_SPLIT_PATTERN.split(answer):
        if not segment.strip():
            continue
        leading = _LEADING_MARKER_RUN.match(segment)
        if leading and units:
            units[-1] = units[-1] + " " + leading.group(1)
            rest = leading.group(2)
            if rest.strip():
                units.append(rest)
        else:
            units.append(segment)
    return units


def _extract_citation_prefixes(text: str) -> list[str]:
    """Extract normalized citation ID prefixes from a text segment."""
    try:
        text = normalize_citation_markers(text)
    except Exception:
        pass
    prefixes: list[str] = []
    for raw in _CITATION_MARKER_PATTERN.findall(text):
        cleaned = raw.strip().lower()
        if not cleaned:
            continue
        prefixes.append(
            cleaned if cleaned.startswith("web_") else cleaned[:8]
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for prefix in prefixes:
        if prefix not in seen:
            seen.add(prefix)
            ordered.append(prefix)
    return ordered


def _resolve_cited_chunks(
    prefixes: list[str],
    chunks: list[EvidenceChunk],
) -> list[EvidenceChunk]:
    """Resolve citation prefixes to retrieved chunks (verifier semantics).

    A prefix matching exactly one chunk resolves to it; a prefix matching
    several (ambiguous) resolves to their union rather than abstaining;
    a prefix matching none resolves to nothing (fail closed downstream).
    """
    resolved: list[EvidenceChunk] = []
    for prefix in prefixes:
        for chunk in chunks:
            if chunk.chunk_id.startswith(prefix) and chunk not in resolved:
                resolved.append(chunk)
    return resolved


def _check_sentence_claims(
    sentence: str,
    evidence_text: str,
    evidence_chunk_ids: list[str],
    geo_seen: set[tuple[str, str]],
) -> list[UnsupportedClaim]:
    """Check one sentence's claims against its evidence text."""
    unsupported: list[UnsupportedClaim] = []
    unsupported.extend(_check_claims(sentence, evidence_text, _extract_numbers, "number", evidence_chunk_ids))
    unsupported.extend(_check_claims(sentence, evidence_text, _extract_dates, "date", evidence_chunk_ids))
    unsupported.extend(_check_claims(sentence, evidence_text, _extract_entities, "entity", evidence_chunk_ids, case_sensitive=False))
    unsupported.extend(_check_claims(sentence, evidence_text, _extract_conditions, "condition", evidence_chunk_ids, case_sensitive=False))
    unsupported.extend(_check_geography_for_sentence(sentence, evidence_text, evidence_chunk_ids, geo_seen))
    return unsupported


def verify_answer_grounding(
    answer: str,
    evidence_chunks: list[EvidenceChunk],
    use_llm_verification: bool = False,
    settings: Any = None,
) -> GroundingResult:
    """Verify that factual claims in the answer are grounded in evidence.

    Layer 1: Regex extraction — extracts numbers, dates, entities, conditions,
    and geographic-scope claims from the answer and checks them against the
    evidence chunks.

    Layer 2 (optional): LLM verification — triggered when Layer 1 finds issues
    and use_llm_verification is True.

    Returns GroundingResult with any unsupported claims found.
    """
    if not answer:
        return GroundingResult()
    if not evidence_chunks:
        # Fail closed: a non-empty answer with zero evidence chunks has
        # no support. The previous vacuous `has_unsupported_claims=False`
        # let unsupported answers verify clean.
        return GroundingResult(
            has_unsupported_claims=True,
            unsupported_claims=[
                UnsupportedClaim(
                    claim_text="(no evidence)",
                    claim_type="evidence",
                    reason="No evidence chunks available to ground the answer",
                )
            ],
        )

    evidence_text = _build_evidence_text(evidence_chunks)
    evidence_chunk_ids = [chunk.chunk_id for chunk in evidence_chunks]

    units = _split_into_cited_units(answer)

    unsupported: list[UnsupportedClaim] = []
    if not any(_extract_citation_prefixes(u) for u in units):
        # No citations anywhere: legacy whole-pool check, byte-identical
        # behavior for citation-free answers.
        unsupported.extend(_check_claims(answer, evidence_text, _extract_numbers, "number", evidence_chunk_ids))
        unsupported.extend(_check_claims(answer, evidence_text, _extract_dates, "date", evidence_chunk_ids))
        unsupported.extend(_check_claims(answer, evidence_text, _extract_entities, "entity", evidence_chunk_ids, case_sensitive=False))
        unsupported.extend(_check_claims(answer, evidence_text, _extract_conditions, "condition", evidence_chunk_ids, case_sensitive=False))
        unsupported.extend(_check_geography(answer, evidence_text, evidence_chunk_ids))
    else:
        # Citation-bound check: each cited unit is verified only
        # against its cited chunks; uncited units keep the pool.
        geo_seen: set[tuple[str, str]] = set()
        for unit in units:
            prefixes = _extract_citation_prefixes(unit)
            if prefixes:
                cited = _resolve_cited_chunks(prefixes, evidence_chunks)
                cited_text = " ".join(chunk.content for chunk in cited)
                cited_ids = [chunk.chunk_id for chunk in cited]
            else:
                cited_text = evidence_text
                cited_ids = evidence_chunk_ids
            unsupported.extend(
                _check_sentence_claims(unit, cited_text, cited_ids, geo_seen)
            )

    # Layer 2: LLM verification (optional, off by default). Claims are
    # re-verified against their own cited chunks only, grouped by cited
    # set so uncited evidence cannot rescue a cited claim here either.
    # Dangling-citation claims (no resolvable evidence) never reach the
    # LLM and stay unsupported.
    if unsupported and use_llm_verification:
        reviewable = [c for c in unsupported if c.evidence_chunk_ids]
        dangling = [c for c in unsupported if not c.evidence_chunk_ids]
        groups: dict[tuple[str, ...], list[UnsupportedClaim]] = {}
        for claim in reviewable:
            key = tuple(sorted(set(claim.evidence_chunk_ids)))
            groups.setdefault(key, []).append(claim)
        by_id = {chunk.chunk_id: chunk for chunk in evidence_chunks}
        rechecked: list[UnsupportedClaim] = []
        for key, group in groups.items():
            group_chunks = [by_id[cid] for cid in key if cid in by_id]
            rechecked.extend(
                verify_with_llm(group, group_chunks or evidence_chunks, settings)
            )
        unsupported = dangling + rechecked

    return GroundingResult(
        has_unsupported_claims=len(unsupported) > 0,
        unsupported_claims=unsupported,
    )
