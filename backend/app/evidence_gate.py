"""Refactored evidence gate using typed contracts.

Implements Stage 7: evidence gate with typed abstention reasons,
calibrated confidence bands, and defense-in-depth checks.

Replaces the monolithic evidence_gate() in retrieval.py with a
composable, testable gate that uses contract types.
"""

from __future__ import annotations

from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    EvidenceChunk,
)

# Domain alias mapping — some classifiers use shorthand names that
# refer to the same conceptual domain as AnchorStore's canonical names.
_DOMAIN_ALIASES: dict[str, set[str]] = {
    "financial_inclusion": {"finlit", "financial_inclusion"},
    "finlit": {"finlit", "financial_inclusion"},
    # PACS family: pacs_governance/pacs_computerization/cooperative/pacs
    # all alias to each other (same conceptual domain). Cross-aliased to
    # pmfby/schemes/agriculture would let a PACS query accept crop-insurance
    # chunks — fixed by this tighten (see test_gate_pacs_isolation).
    "pacs_governance": {"pacs_governance", "pacs_computerization", "cooperative", "pacs"},
    "pacs_computerization": {"pacs_governance", "pacs_computerization", "cooperative", "pacs"},
    "cooperative": {"pacs_governance", "pacs_computerization", "cooperative", "pacs"},
    "pacs": {"pacs_governance", "pacs_computerization", "cooperative", "pacs"},
    # schemes <-> pmfby kept: corpus gap requires it.
    "schemes": {"schemes", "pmfby"},
    "pmfby": {"schemes", "pmfby"},
    # agriculture -> pmfby kept: corpus gap requires it.
    "agriculture": {"agriculture", "pmfby"},
}


def _domain_matches(chunk_domain: str, expected_domain: str) -> bool:
    """Check if chunk domain matches expected domain, considering aliases."""
    if chunk_domain == expected_domain:
        return True
    expected_aliases = _DOMAIN_ALIASES.get(expected_domain)
    if expected_aliases and chunk_domain in expected_aliases:
        return True
    chunk_aliases = _DOMAIN_ALIASES.get(chunk_domain)
    if chunk_aliases and expected_domain in chunk_aliases:
        return True
    return False


def evidence_gate(
    chunks: list[EvidenceChunk],
    expected_domain: str,
    expected_state: str | None = None,
    min_chunks: int = 2,
    min_confidence: float = 0.25,
) -> tuple[bool, AbstentionReason | None, ConfidenceBand | None]:
    """Unified evidence gate accepting EvidenceChunk lists.

    Filters by domain, jurisdiction, chunk count, and score thresholds.
    Returns (abstained, reason, confidence_band).

    Defense-in-depth:
    1. Domain filter: chunks must match expected_domain
    2. Jurisdiction filter: state-level chunks must match expected_state;
       central-level chunks match all states
    3. Chunk count: at least min_chunks must survive filtering
    4. Score check: top score must meet min_confidence
    """
    if not chunks:
        return True, AbstentionReason.NO_ELIGIBLE_SOURCE, ConfidenceBand.LOW

    # Domain filter — use alias-aware matching so "finlit" matches "financial_inclusion"
    domain_chunks = [c for c in chunks if _domain_matches(c.domain, expected_domain)]
    if not domain_chunks:
        return True, AbstentionReason.DOMAIN_MISMATCH, ConfidenceBand.LOW

    # Jurisdiction filter:
    # - central chunks pass under any expected_state (central content is valid everywhere)
    # - state chunks pass when expected_state is set AND the chunk's state matches
    # - state chunks with no state field pass when expected_state is None (no state filter requested);
    #   the chunk's state is unknown but the user did not ask for a specific state
    # - state chunks with a mismatched state are dropped (they don't answer the requested state)
    jurisdiction_chunks: list[EvidenceChunk] = []
    for c in domain_chunks:
        if c.jurisdiction == "central":
            jurisdiction_chunks.append(c)
        elif expected_state and c.state == expected_state:
            jurisdiction_chunks.append(c)
        elif not expected_state and c.jurisdiction == "state" and c.state is None:
            # State-jurisdiction chunk with unknown state, no state filter requested — pass.
            # We cannot verify which state the chunk belongs to, but the user did not ask
            # for a specific state, so rejection would discard potentially relevant evidence.
            jurisdiction_chunks.append(c)
        elif not expected_state and c.jurisdiction == "unknown":
            # Unknown-jurisdiction chunk (no per-source or classification jurisdiction signal).
            # With no state filter requested, this chunk is not proven state-specific — pass
            # for consideration but at lower effective weight (the score check still applies).
            jurisdiction_chunks.append(c)
        # else: state-level chunk with mismatched state — drop it

    if not jurisdiction_chunks:
        return True, AbstentionReason.JURISDICTION_MISMATCH, ConfidenceBand.LOW

    # Chunk count check
    if len(jurisdiction_chunks) < min_chunks:
        return True, AbstentionReason.INSUFFICIENT_SUPPORTING_CHUNKS, ConfidenceBand.LOW

    # Score check — use dense_score as primary, fallback to rerank_score
    scores = sorted(
        (c.dense_score or c.rerank_score or 0.0 for c in jurisdiction_chunks),
        reverse=True,
    )
    if scores[0] < min_confidence:
        return True, AbstentionReason.BELOW_TOP1_THRESHOLD, ConfidenceBand.LOW

    # Compute confidence band
    band = _compute_band_from_scores(scores)
    return False, None, band




def _compute_band_from_scores(scores: list[float]) -> ConfidenceBand:
    """Compute confidence band from sorted descending scores."""
    if not scores:
        return ConfidenceBand.LOW

    top1 = scores[0]
    secondary_threshold = 0.30
    strong = sum(1 for s in scores if s >= secondary_threshold)
    total = len(scores)

    if top1 >= 0.50 and strong >= 3 and strong / max(total, 1) >= 0.5:
        return ConfidenceBand.HIGH
    elif top1 >= 0.35 and strong >= 2:
        return ConfidenceBand.MEDIUM
    else:
        return ConfidenceBand.LOW
