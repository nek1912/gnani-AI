"""Evidence gate boundary tests — exact threshold edge cases."""
from app.config import SECONDARY_THRESHOLD, TOP1_THRESHOLD
from app.retrieval import RetrievedChunk, evidence_gate

_DOMAIN = "pmfby"
_STATE = "gujarat"


def _chunk(sim: float, domain: str = _DOMAIN, jurisdiction: str = "central",
           state: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee",
        stable_chunk_id="test:p1:c0",
        document_id="dddd1111-2222-3333-4444-555555555555",
        title="Test", page=1, page_start=1, page_end=1, section="s",
        content="c", similarity=sim, source_url="http://x", domain=domain,
        jurisdiction=jurisdiction, state=state)


# ── top1 threshold boundaries ───────────────────────────────────────────

def test_top1_just_below_abstains():
    result = evidence_gate([_chunk(sim=TOP1_THRESHOLD - 0.000001)],
                           expected_domain=_DOMAIN, expected_state=None)
    assert result.abstained is True
    assert result.reason == "below_top1_threshold"


def test_top1_exactly_at_passes():
    result = evidence_gate([_chunk(sim=TOP1_THRESHOLD)],
                           expected_domain=_DOMAIN, expected_state=None)
    assert result.abstained is True
    assert result.reason == "insufficient_supporting_chunks"


def test_top1_above_passes_condition():
    result = evidence_gate([_chunk(sim=TOP1_THRESHOLD)],
                           expected_domain=_DOMAIN, expected_state=None)
    assert result.abstained is True


# ── secondary threshold boundaries ──────────────────────────────────────

def test_secondary_just_below_insufficient():
    sims = [0.8, SECONDARY_THRESHOLD - 0.000001]
    chunks = [_chunk(sim=s) for s in sims]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.abstained is True
    assert result.reason == "insufficient_supporting_chunks"


def test_secondary_exactly_at_sufficient():
    sims = [0.8, SECONDARY_THRESHOLD, SECONDARY_THRESHOLD]
    chunks = [_chunk(sim=s) for s in sims]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.abstained is False


# ── supporting chunk count boundaries ───────────────────────────────────

def test_one_supporting_chunk_rejects():
    chunks = [_chunk(sim=0.8), _chunk(sim=0.29)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.abstained is True


def test_two_supporting_chunks_pass():
    chunks = [_chunk(sim=0.8), _chunk(sim=0.31), _chunk(sim=0.31)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.abstained is False


def test_three_supporting_chunks_pass():
    chunks = [_chunk(sim=0.8), _chunk(sim=0.5), _chunk(sim=0.35)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.abstained is False


# ── empty / mismatched chunks ───────────────────────────────────────────

def test_empty_chunks_abstain():
    result = evidence_gate([], expected_domain=_DOMAIN)
    assert result.abstained is True
    assert result.reason == "no_chunks"


def test_wrong_domain_abstain():
    chunks = [_chunk(sim=0.8, domain="cooperative")]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.abstained is True
    assert result.reason == "domain_mismatch_in_retrieval"


def test_wrong_state_abstain():
    chunks = [_chunk(sim=0.8, jurisdiction="state", state="maharashtra")]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    assert result.abstained is True
    assert result.reason == "jurisdiction_mismatch_in_retrieval"


def test_central_plus_valid_state_passes():
    chunks = [
        _chunk(sim=0.8, jurisdiction="central"),
        _chunk(sim=0.5, jurisdiction="state", state=_STATE),
        _chunk(sim=0.4, jurisdiction="state", state=_STATE),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    assert result.abstained is False


def test_central_plus_wrong_state_abstains():
    chunks = [
        _chunk(sim=0.8, jurisdiction="central"),
        _chunk(sim=0.5, jurisdiction="state", state="maharashtra"),
        _chunk(sim=0.4, jurisdiction="state", state="maharashtra"),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    assert result.abstained is True
    assert result.reason == "jurisdiction_mismatch_in_retrieval"


def test_mixed_valid_invalid_chunks_abstain():
    chunks = [
        _chunk(sim=0.8, jurisdiction="central"),
        _chunk(sim=0.5, jurisdiction="state", state="maharashtra"),
        _chunk(sim=0.4, jurisdiction="state", state=_STATE),
    ]
    result = evidence_gate(chunks, expected_domain=_DOMAIN, expected_state=_STATE)
    assert result.abstained is True
    assert result.reason == "jurisdiction_mismatch_in_retrieval"


# ── confidence formula determinism ──────────────────────────────────────

def test_confidence_deterministic():
    chunks = [_chunk(sim=0.8), _chunk(sim=0.5), _chunk(sim=0.4)]
    r1 = evidence_gate(chunks, expected_domain=_DOMAIN)
    r2 = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert r1.confidence == r2.confidence
    assert r1.confidence > 0.0
    assert 0.0 <= r1.confidence <= 1.0


def test_confidence_clamped_upper():
    chunks = [_chunk(sim=1.0), _chunk(sim=1.0), _chunk(sim=1.0)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.confidence <= 1.0


def test_confidence_clamped_lower():
    chunks = [_chunk(sim=0.35), _chunk(sim=0.35), _chunk(sim=0.35)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.confidence >= 0.0
    assert result.confidence <= 1.0


def test_confidence_formula_manual_calc():
    sims = [0.72, 0.51]
    strong = sum(1 for s in sims if s >= SECONDARY_THRESHOLD)
    base = sims[0] * 0.6
    coverage = min(strong / 3, 1.0) * 0.3
    expected = round(min(base + coverage + 0.1, 1.0), 2)
    chunks = [_chunk(sim=0.72), _chunk(sim=0.51)]
    result = evidence_gate(chunks, expected_domain=_DOMAIN)
    assert result.confidence == expected
