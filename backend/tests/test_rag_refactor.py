"""Tests for refactored RAG components: evidence gate, citation verifier."""


from app.contracts import (
    AbstentionReason,
    RetrievalCandidate,
)
from app.services.static_rag import _reciprocal_rank_fusion as reciprocal_rank_fusion
from app.citation_verifier import (
    extract_citations_from_answer,
    verify_citation_ids,
    verify_claims_supported,
    verify_citations,
    verify_no_fabricated_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(
    chunk_id: str = "abc12345def",
    document_id: str = "doc-001",
    source_id: str = "src-001",
    dense_score: float = 0.5,
    lexical_score: float = 0.5,
    domain: str = "schemes",
    is_central: bool = True,
    state_match: bool = True,
    **kwargs,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id=document_id,
        source_id=source_id,
        dense_score=dense_score,
        lexical_score=lexical_score,
        filter_decisions={"domain": True, "active": True, "is_central": is_central, "state_match": state_match, **kwargs},
    )


# ---------------------------------------------------------------------------
# Hybrid Retrieval (RRF fusion)
# ---------------------------------------------------------------------------

class TestHybridRetrieval:
    def test_rrf_fusion_deterministic(self):
        dense = [_make_candidate("a", dense_score=0.9), _make_candidate("b", dense_score=0.8)]
        lexical = [_make_candidate("b", lexical_score=0.9), _make_candidate("a", lexical_score=0.8)]

        result1 = reciprocal_rank_fusion(dense, lexical)
        result2 = reciprocal_rank_fusion(dense, lexical)
        assert [r.chunk_id for r in result1] == [r.chunk_id for r in result2]

    def test_rrf_prefers_both_components(self):
        dense = [_make_candidate("a", dense_score=0.9), _make_candidate("b", dense_score=0.8)]
        lexical = [_make_candidate("a", lexical_score=0.9), _make_candidate("b", lexical_score=0.8)]

        result = reciprocal_rank_fusion(dense, lexical)
        assert result[0].chunk_id == "a"

    def test_rrf_tie_breaking_deterministic(self):
        c1 = _make_candidate("aaa", document_id="doc-001", dense_score=0.5)
        c2 = _make_candidate("bbb", document_id="doc-001", dense_score=0.5)
        c3 = _make_candidate("ccc", document_id="doc-002", dense_score=0.5)

        dense = [c1, c2, c3]
        lexical = [c1, c2, c3]

        result = reciprocal_rank_fusion(dense, lexical)
        ids = [r.chunk_id for r in result]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Citation Verifier
# ---------------------------------------------------------------------------

class TestCitationVerifier:
    def test_extract_citations(self):
        answer = "PMFBY is good [chunk:abc12345def] and [chunk:abc1234500] are citations"
        citations = extract_citations_from_answer(answer)
        assert len(citations) == 2
        assert citations[0][1] == "abc12345"

    def test_verify_valid_citations(self):
        answer = "Answer [chunk:abc12345def]"
        valid, invalid = verify_citation_ids(answer, ["abc12345def", "xyz98765abc"])
        assert len(valid) == 1
        assert len(invalid) == 0

    def test_verify_invalid_citations(self):
        answer = "Answer [chunk:fffffffffff]"
        valid, invalid = verify_citation_ids(answer, ["abc12345def"])
        assert len(valid) == 0
        assert "ffffffff" in invalid

    def test_verify_mixed_citations(self):
        answer = "Good [chunk:abc12345def] bad [chunk:fffffffffff]"
        valid, invalid = verify_citation_ids(answer, ["abc12345def"])
        assert len(valid) == 1
        assert len(invalid) == 1

    def test_no_fabricated_urls(self):
        answer = "Visit https://example.com for more"
        issues = verify_no_fabricated_content(answer)
        assert len(issues) == 1
        assert "fabricated URL" in issues[0]

    def test_no_non_citation_markers(self):
        answer = "See [Source 1] for details"
        issues = verify_no_fabricated_content(answer)
        assert len(issues) == 1
        assert "non-citation marker" in issues[0]

    def test_claims_supported(self):
        from app.contracts import AtomicClaim
        claims = [AtomicClaim(
            claim_text="PMFBY exists",
            evidence_chunk_ids=["abc12345def"],
            is_supported=True,
        )]
        unsupported = verify_claims_supported(claims, ["abc12345def"])
        assert len(unsupported) == 0

    def test_claims_unsupported(self):
        from app.contracts import AtomicClaim
        claims = [AtomicClaim(
            claim_text="Something",
            evidence_chunk_ids=["fffffffffff"],
        )]
        unsupported = verify_claims_supported(claims, ["abc12345def"])
        assert len(unsupported) == 1

    def test_full_verification_valid(self):
        answer = "PMFBY [chunk:abc12345def]"
        result = verify_citations(answer, ["abc12345def"])
        assert result.is_valid is True
        assert len(result.valid_citations) == 1

    def test_full_verification_invalid(self):
        answer = "PMFBY [chunk:fffffffffff]"
        result = verify_citations(answer, ["abc12345def"])
        assert result.is_valid is False
        assert result.reason == AbstentionReason.CITATION_FAILURE

    def test_full_verification_no_citations(self):
        answer = "PMFBY is great"
        result = verify_citations(answer, ["abc12345def"])
        assert result.is_valid is False
        assert result.reason == AbstentionReason.CITATION_FAILURE
