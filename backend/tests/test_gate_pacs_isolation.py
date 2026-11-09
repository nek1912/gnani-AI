"""Task 5: PACS-domain gate isolation (test-first).

PACS governance queries must reject pmfby/schemes chunks, and pmfby/schemes
queries must reject pacs_governance chunks. The current _DOMAIN_ALIASES in
evidence_gate.py lets pmfby<->schemes and agriculture<->pmfby cross-accept,
so PACS vs pmfby isolation is broken. These tests fail until aliases are
tightened (see evidence_gate.py).
"""

from app.contracts import AbstentionReason, EvidenceChunk
from app.evidence_gate import evidence_gate


def _c(domain: str, score: float = 0.8) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=f"x-{domain}",
        content="test content",
        source_type="static",
        title="t",
        domain=domain,
        jurisdiction="central",
        dense_score=score,
    )


# ── PACS must reject pmfby/schemes ─────────────────────────────────────────

def test_pacs_rejects_pmfby():
    abstained, reason, _ = evidence_gate(
        [_c("pmfby")], expected_domain="pacs_governance", min_chunks=1
    )
    assert abstained is True
    assert reason == AbstentionReason.DOMAIN_MISMATCH


def test_pacs_rejects_schemes():
    abstained, reason, _ = evidence_gate(
        [_c("schemes")], expected_domain="pacs_governance", min_chunks=1
    )
    assert abstained is True
    assert reason == AbstentionReason.DOMAIN_MISMATCH


def test_pacs_accepts_cooperative():
    # cooperative <-> pacs alias is intended
    abstained, reason, _ = evidence_gate(
        [_c("cooperative")], expected_domain="pacs_governance", min_chunks=1
    )
    assert abstained is False


# ── pmfby must reject pacs_governance ──────────────────────────────────────

def test_pmfby_rejects_pacs_governance():
    abstained, reason, _ = evidence_gate(
        [_c("pacs_governance")], expected_domain="pmfby", min_chunks=1
    )
    assert abstained is True
    assert reason == AbstentionReason.DOMAIN_MISMATCH


def test_pmfby_rejects_pacs_computerization():
    abstained, reason, _ = evidence_gate(
        [_c("pacs_computerization")], expected_domain="pmfby", min_chunks=1
    )
    assert abstained is True
    assert reason == AbstentionReason.DOMAIN_MISMATCH


# ── pacs_computerization isolation ─────────────────────────────────────────

def test_pacs_computerization_rejects_pmfby():
    abstained, reason, _ = evidence_gate(
        [_c("pmfby")], expected_domain="pacs_computerization", min_chunks=1
    )
    assert abstained is True
    assert reason == AbstentionReason.DOMAIN_MISMATCH


def test_pacs_computerization_accepts_cooperative():
    abstained, reason, _ = evidence_gate(
        [_c("cooperative")], expected_domain="pacs_computerization", min_chunks=1
    )
    assert abstained is False


# ── existing scheme<->pmfby and agriculture<->pmfby aliases kept ───────────

def test_pmfby_still_accepts_schemes():
    abstained, reason, _ = evidence_gate(
        [_c("schemes")], expected_domain="pmfby", min_chunks=1
    )
    assert abstained is False


def test_schemes_still_accepts_pmfby():
    abstained, reason, _ = evidence_gate(
        [_c("pmfby")], expected_domain="schemes", min_chunks=1
    )
    assert abstained is False


def test_agriculture_still_accepts_pmfby():
    abstained, reason, _ = evidence_gate(
        [_c("pmfby")], expected_domain="agriculture", min_chunks=1
    )
    assert abstained is False
