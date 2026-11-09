"""Tests for the unified evidence_gate() accepting EvidenceChunk lists."""
from app.contracts import AbstentionReason, ConfidenceBand, EvidenceChunk
from app.evidence_gate import evidence_gate

_DOMAIN = "pmfby"
_STATE = "gujarat"


def _chunk(
    score: float,
    domain: str = _DOMAIN,
    jurisdiction: str = "central",
    state: str | None = None,
    chunk_id: str = "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee",
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content="test content",
        source_type="static",
        title="Test",
        domain=domain,
        jurisdiction=jurisdiction,
        state=state,
        dense_score=score,
    )


# ── empty / no chunks ────────────────────────────────────────────────────

def test_empty_chunks_abstains():
    result = evidence_gate([], expected_domain=_DOMAIN)
    assert result == (True, AbstentionReason.NO_ELIGIBLE_SOURCE, ConfidenceBand.LOW)


# ── domain mismatch ──────────────────────────────────────────────────────

def test_wrong_domain_abstains():
    chunks = [_chunk(0.8, domain="cooperative")]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result == (True, AbstentionReason.DOMAIN_MISMATCH, ConfidenceBand.LOW)


def test_matching_domain_passes():
    chunks = [_chunk(0.8), _chunk(0.5), _chunk(0.4)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result[0] is False
    assert result[1] is None


# ── jurisdiction mismatch ────────────────────────────────────────────────

def test_wrong_state_abstains():
    chunks = [
        _chunk(0.8, jurisdiction="state", state="maharashtra"),
        _chunk(0.5, jurisdiction="state", state="maharashtra"),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    assert result == (True, AbstentionReason.JURISDICTION_MISMATCH, ConfidenceBand.LOW)


def test_central_matches_all_states():
    chunks = [
        _chunk(0.8, jurisdiction="central"),
        _chunk(0.5, jurisdiction="central"),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    assert result[0] is False
    assert result[1] is None


def test_central_plus_matching_state_passes():
    chunks = [
        _chunk(0.8, jurisdiction="central"),
        _chunk(0.5, jurisdiction="state", state=_STATE),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    assert result[0] is False


def test_central_plus_wrong_state_abstains():
    chunks = [
        _chunk(0.8, jurisdiction="central"),
        _chunk(0.5, jurisdiction="state", state="maharashtra"),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    # Central passes jurisdiction, but wrong-state chunk is dropped
    # Only 1 jurisdiction-eligible chunk remains — below min_chunks=2
    assert result == (True, AbstentionReason.INSUFFICIENT_SUPPORTING_CHUNKS, ConfidenceBand.LOW)


def test_no_expected_state_uses_only_central():
    chunks = [
        _chunk(0.8, jurisdiction="state", state=_STATE),
    ]
    # No expected_state provided — state-level chunks don't match
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result[0] is True
    assert result[1] in (AbstentionReason.JURISDICTION_MISMATCH, AbstentionReason.INSUFFICIENT_SUPPORTING_CHUNKS)


# ── chunk count ──────────────────────────────────────────────────────────

def test_insufficient_chunks_abstains():
    chunks = [_chunk(0.8)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, min_chunks=2)
    assert result == (True, AbstentionReason.INSUFFICIENT_SUPPORTING_CHUNKS, ConfidenceBand.LOW)


def test_custom_min_chunks():
    chunks = [_chunk(0.8), _chunk(0.5)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, min_chunks=3)
    assert result == (True, AbstentionReason.INSUFFICIENT_SUPPORTING_CHUNKS, ConfidenceBand.LOW)


def test_enough_chunks_passes():
    chunks = [_chunk(0.8), _chunk(0.5), _chunk(0.4)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, min_chunks=2)
    assert result[0] is False
    assert result[1] is None


# ── score thresholds ─────────────────────────────────────────────────────

def test_below_min_confidence_abstains():
    chunks = [_chunk(0.10), _chunk(0.10)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, min_confidence=0.25)
    assert result == (True, AbstentionReason.BELOW_TOP1_THRESHOLD, ConfidenceBand.LOW)


def test_exactly_at_min_confidence_passes():
    chunks = [_chunk(0.25), _chunk(0.30)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, min_confidence=0.25)
    assert result[0] is False
    assert result[1] is None


def test_above_min_confidence_passes():
    chunks = [_chunk(0.80), _chunk(0.50)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, min_confidence=0.25)
    assert result[0] is False


def test_rerank_score_fallback():
    chunk = EvidenceChunk(
        chunk_id="test1",
        content="test",
        source_type="static",
        domain=_DOMAIN,
        jurisdiction="central",
        dense_score=None,
        rerank_score=0.60,
    )
    chunk2 = EvidenceChunk(
        chunk_id="test2",
        content="test",
        source_type="static",
        domain=_DOMAIN,
        jurisdiction="central",
        dense_score=None,
        rerank_score=0.50,
    )
    result = evidence_gate([chunk, chunk2], expected_domain=_DOMAIN, min_confidence=0.25)
    assert result[0] is False


# ── confidence bands ─────────────────────────────────────────────────────

def test_high_band():
    chunks = [_chunk(0.80), _chunk(0.60), _chunk(0.50), _chunk(0.40)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result[0] is False
    assert result[2] == ConfidenceBand.HIGH


def test_medium_band():
    chunks = [_chunk(0.40), _chunk(0.35), _chunk(0.30)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result[0] is False
    assert result[2] == ConfidenceBand.MEDIUM


def test_low_band():
    chunks = [_chunk(0.30), _chunk(0.20)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result[0] is False
    assert result[2] == ConfidenceBand.LOW


# ── mixed domains + jurisdictions ────────────────────────────────────────

def test_mixed_domain_chunks_filters_correctly():
    chunks = [
        _chunk(0.80, domain=_DOMAIN, jurisdiction="central"),
        _chunk(0.70, domain="cooperative", jurisdiction="central"),
        _chunk(0.50, domain=_DOMAIN, jurisdiction="central"),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result[0] is False
    assert result[1] is None
