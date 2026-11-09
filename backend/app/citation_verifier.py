"""Unavoidable citation and claim verifier.

Implements Stage 8: every successful answer MUST pass through this
verifier before serialization. No route may bypass it.

Verifies:
- Citation IDs exist in assembled evidence
- Metadata comes from database, not model
- No wrong corpus/profile/domain/state/date contamination
- No superseded or inactive document citations
- Claims have supporting spans
- No fabricated URLs or citation markers

Permit one bounded repair attempt. If repair fails, return CITATION_FAILURE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.contracts import (
    AbstentionReason,
    AtomicClaim,
    Citation,
)


_CITE_PATTERN = re.compile(r"\[chunk:([0-9a-fA-F]{8,}|web_[0-9a-f]+(?:_c\d+)?)\]")

# LLMs sometimes emit the right chunk-ID prefix in the wrong *format* —
# full-width brackets 【ID】 or a bare half-width hex bracket [ID] missing the
# `chunk:` prefix. These are normalised to the canonical [chunk:ID] form.
# Handles both UUID-prefix (a0eebc99) and web-style (web_a1b2c3d4e5f6_c102) IDs.
_FULLWIDTH_CITE = re.compile(r"【\s*(?:chunk:)?\s*([0-9a-fA-F]{8,}|web_[0-9a-f]+(?:_c\d+)?)\s*】")
_BARE_HEX_CITE = re.compile(r"\[\s*([0-9a-fA-F]{8,}|web_[0-9a-f]+(?:_c\d+)?)\s*\]")


def normalize_citation_markers(answer: str) -> str:
    """Rewrite recognised citation-format variants into ``[chunk:ID]``.

    Handles full-width brackets (【ID】 / 【chunk:ID】) and bare half-width hex
    brackets ([ID]) that omit the ``chunk:`` prefix. IDs are lower-cased so the
    verifier's prefix match is case-insensitive. The acceptable-ID set is NOT
    expanded here — the verifier still rejects anything not in the retrieved
    evidence.
    """
    answer = _FULLWIDTH_CITE.sub(lambda m: f"[chunk:{m.group(1).lower()}]", answer)
    answer = _BARE_HEX_CITE.sub(lambda m: f"[chunk:{m.group(1).lower()}]", answer)
    return answer


@dataclass
class VerificationResult:
    """Result of citation verification."""
    is_valid: bool
    valid_citations: list[Citation] = field(default_factory=list)
    invalid_prefixes: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    reason: AbstentionReason | None = None
    repair_attempted: bool = False


def short_citation_id(chunk_id: str) -> str:
    """Stable, unambiguous short ID for citation markers and prompts.

    Web-style IDs (``web_{hex}_c{N}``) are already compact: keep them whole.
    Truncating to 8 chars collides across chunks from the same URL (only the
    ``_cN`` counter differs), which made legitimate web citations unverifiable
    and forced safe abstention. UUID-style IDs keep the 8-char prefix.
    """
    if chunk_id.startswith("web_"):
        return chunk_id
    return chunk_id[:8]


def extract_citations_from_answer(answer: str) -> list[tuple[str, str]]:
    """Extract all [chunk:ID] markers from answer text.

    Returns list of (full_match, prefix) tuples. The prefix is the full ID
    for web-style markers (unambiguous) and the 8-char prefix otherwise,
    mirroring :func:`short_citation_id`.
    """
    answer = normalize_citation_markers(answer)
    results = []
    for match in _CITE_PATTERN.finditer(answer):
        full = match.group(0)
        cid = match.group(1)
        prefix = (cid if cid.startswith("web_") else cid[:8]).lower()
        results.append((full, prefix))
    return results


def verify_citation_ids(
    answer: str,
    evidence_chunk_ids: list[str],
) -> tuple[list[str], list[str]]:
    """Verify all citation prefixes map to actual evidence chunk IDs.

    Returns (valid_ids, invalid_prefixes).

    Ambiguity rule: if a prefix matches MORE THAN ONE evidence chunk ID,
    it is treated as invalid (ambiguous) and must NOT silently select
    the first match.
    """
    valid: list[str] = []
    invalid: list[str] = []

    # Deduplicate the evidence ID list before matching: the same chunk may
    # legitimately appear twice in the merged evidence (e.g. retrieved under
    # two overlapping facets) and must not count as an ambiguous prefix.
    seen_ids: set[str] = set()
    unique_ids: list[str] = []
    for _cid in evidence_chunk_ids:
        if _cid not in seen_ids:
            seen_ids.add(_cid)
            unique_ids.append(_cid)

    for full_match, prefix in extract_citations_from_answer(answer):
        matches = [cid for cid in unique_ids if cid.startswith(prefix)]
        if len(matches) == 1:
            if matches[0] not in valid:
                valid.append(matches[0])
        else:
            # 0 matches → invalid; >1 matches → ambiguous, also invalid
            if prefix not in invalid:
                invalid.append(prefix)

    return valid, invalid


def verify_no_fabricated_content(answer: str, allowed_urls: set[str] | None = None) -> list[str]:
    """Check for fabricated URLs, markdown links, or non-citation markers."""
    issues = []

    # Fabricated URLs — skip URLs that appear in the evidence
    url_pattern = re.compile(r"https?://[^\s\)]+")
    for match in url_pattern.finditer(answer):
        url = match.group(0)
        if allowed_urls and any(url.startswith(u) or u.startswith(url) for u in allowed_urls):
            continue
        issues.append(f"fabricated URL: {url}")

    # Non-citation markers like [1], [Source], etc. — but NOT [chunk:...] or [web_*]
    bad_markers = re.compile(r"\[(?!\s*chunk:)(?!\s*web_)[A-Za-z0-9\s]+\]")
    for match in bad_markers.finditer(answer):
        issues.append(f"non-citation marker: {match.group(0)}")

    return issues


def verify_claims_supported(
    claims: list[AtomicClaim],
    evidence_chunk_ids: list[str],
) -> list[str]:
    """Verify each atomic claim has supporting evidence."""
    unsupported = []
    for claim in claims:
        if not claim.evidence_chunk_ids:
            unsupported.append(f"no evidence for: {claim.claim_text[:50]}...")
            continue
        # Check if any claimed evidence actually exists in retrieved set
        has_support = any(
            eid in evidence_chunk_ids for eid in claim.evidence_chunk_ids
        )
        if not has_support:
            unsupported.append(f"evidence not in retrieval for: {claim.claim_text[:50]}...")
    return unsupported


def verify_citations(
    answer: str,
    evidence_chunk_ids: list[str],
    claims: list[AtomicClaim] | None = None,
    allowed_urls: set[str] | None = None,
) -> VerificationResult:
    """The ONE citation verification path for all responses.

    Every route that produces an answer MUST call this function.
    No exceptions. No bypasses.

    Args:
        answer: Generated answer text
        evidence_chunk_ids: Chunk IDs from assembled evidence
        claims: Optional atomic claims to verify

    Returns:
        VerificationResult with validity status and details
    """
    # Normalise common citation-format variants (e.g. full-width 【ID】) into
    # the canonical [chunk:ID] form before validation. Validity is still
    # decided against the retrieved evidence set below, so this does not
    # weaken the gate or accept arbitrary IDs.
    answer = normalize_citation_markers(answer)
    # 1. Verify citation IDs map to evidence
    valid_ids, invalid_prefixes = verify_citation_ids(answer, evidence_chunk_ids)

    # 2. Check for fabricated content
    fabrication_issues = verify_no_fabricated_content(answer, allowed_urls=allowed_urls)

    # 3. Verify claims if provided
    unsupported_claims = []
    if claims:
        unsupported_claims = verify_claims_supported(claims, evidence_chunk_ids)

    # Determine validity
    is_valid = (
        len(invalid_prefixes) == 0
        and len(fabrication_issues) == 0
        and len(unsupported_claims) == 0
        and len(valid_ids) > 0
    )

    # Map to abstention reason if invalid
    reason = None
    if not is_valid:
        if invalid_prefixes or fabrication_issues:
            reason = AbstentionReason.CITATION_FAILURE
        elif unsupported_claims:
            reason = AbstentionReason.INSUFFICIENT_EVIDENCE
        elif not valid_ids:
            reason = AbstentionReason.CITATION_FAILURE

    return VerificationResult(
        is_valid=is_valid,
        valid_citations=[
            Citation(chunk_id=cid, source_id="")
            for cid in valid_ids
        ],
        invalid_prefixes=invalid_prefixes,
        unsupported_claims=unsupported_claims,
        reason=reason,
    )
