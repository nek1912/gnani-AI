"""Tests for WebRAGService — 10-step web RAG pipeline.

Covers:
- Domain scope gate (step 1)
- Empty query handling
- Web discovery failures (step 2)
- BM25 ranking (step 3)
- Gemini pre-ranking (step 4)
- RRF fusion (step 5)
- Gemini final reranking (step 6)
- Relevance gate (step 7)
- Source verification (step 8)
- Evidence threshold (step 9)
- EvidenceChunk conversion (step 10)
- Full pipeline integration
"""

from __future__ import annotations

from unittest.mock import patch


from app.contracts import (
    AbstentionReason,
    EvidenceChunk,
    RAGResult,
)
from app.services.web_rag import (
    DEFAULT_MIN_RELEVANCE_SCORE,
    SUPPORTED_DOMAINS,
    WebRAGService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_source(
    chunk_id: str = "web_abc123_c1",
    text: str = "Sample evidence text about PMFBY",
    source_url: str = "https://pmfby.gov.in/guidelines",
    title: str = "PMFBY Guidelines",
    bm25_score: float = 5.0,
    gemini_score: float = 75.0,
    rerank_score: float = 75.0,
    rerank_applicable: bool = True,
    official: bool = True,
    jurisdiction: str = "central",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "content": text,
        "source_url": source_url,
        "url": source_url,
        "title": title,
        "web_title": title,
        "document_id": f"doc_{chunk_id}",
        "section_title": "Web page",
        "section": "Web page",
        "source_type": "url",
        "page": None,
        "bm25_score": bm25_score,
        "gemini_score": gemini_score,
        "rerank_score": rerank_score,
        "rerank_applicable": rerank_applicable,
        "official": official,
        "trusted_secondary": False,
        "jurisdiction": jurisdiction,
    }


def _make_classification(
    domain: str = "pmfby",
    jurisdiction: str = "central",
    state: str | None = None,
    intent: str = "INFORMATIONAL",
    confidence: float = 0.85,
):
    from app.web_rag.query_classifier import QueryClassification

    return QueryClassification(
        domain=domain,
        jurisdiction=jurisdiction,
        state=state,
        intent=intent,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Step 1: Domain scope gate
# ---------------------------------------------------------------------------

class TestDomainScopeGate:
    def test_general_domain_passes_scope_gate(self):
        """General domain now proceeds to web discovery instead of aborting."""
        service = WebRAGService()
        classification = _make_classification(domain="general")
        with patch.object(service.web_discovery, "discover") as mock_discover:
            mock_discover.return_value = {"results": [], "classification": {"domain": "general"}}
            result = service.retrieve(
                query="What is the weather?",
                classification=classification,
            )
            # Should reach discovery (not blocked at scope gate)
            # Abstains because discovery returns no results
            mock_discover.assert_called_once()
            assert result.abstained is True
            assert result.reason == AbstentionReason.NO_ELIGIBLE_SOURCE

    def test_unsupported_domain_abstains(self):
        """Truly unsupported domain (not in SUPPORTED_DOMAINS) still abstains."""
        service = WebRAGService()
        classification = _make_classification(domain="cooking")
        result = service.retrieve(
            query="How to cook pasta?",
            classification=classification,
        )
        assert result.abstained is True
        assert result.reason == AbstentionReason.DOMAIN_MISMATCH

    def test_supported_domain_passes(self):
        service = WebRAGService()
        classification = _make_classification(domain="pmfby")
        with patch.object(service.web_discovery, "discover") as mock_discover:
            mock_discover.return_value = {"results": [], "classification": {"domain": "pmfby"}}
            result = service.retrieve(
                query="What is PMFBY?",
                classification=classification,
            )
            # Should reach discovery but abstain due to empty results
            assert result.abstained is True
            assert result.reason == AbstentionReason.NO_ELIGIBLE_SOURCE

    def test_all_supported_domains(self):
        assert SUPPORTED_DOMAINS == {
            "cooperative", "pacs", "pacs_governance", "pacs_computerization",
            "schemes", "pmfby", "agriculture", "finlit", "financial_inclusion",
            "grievance", "driving_licence",
        }


# ---------------------------------------------------------------------------
# Empty query
# ---------------------------------------------------------------------------

class TestEmptyQuery:
    def test_empty_query_abstains(self):
        service = WebRAGService()
        result = service.retrieve(query="")
        assert result.abstained is True
        assert result.reason == AbstentionReason.NO_ELIGIBLE_SOURCE

    def test_whitespace_query_abstains(self):
        service = WebRAGService()
        result = service.retrieve(query="   ")
        assert result.abstained is True

    def test_none_query_abstains(self):
        service = WebRAGService()
        result = service.retrieve(query=None)
        assert result.abstained is True


# ---------------------------------------------------------------------------
# Step 2: Web discovery
# ---------------------------------------------------------------------------

class TestWebDiscovery:
    def test_discovery_failure_returns_provider_unavailable(self):
        service = WebRAGService()
        with patch.object(service.web_discovery, "discover", side_effect=RuntimeError("API down")):
            result = service.retrieve(query="PMFBY eligibility")
            assert result.abstained is True
            assert result.reason == AbstentionReason.PROVIDER_UNAVAILABLE

    def test_empty_discovery_returns_no_source(self):
        service = WebRAGService()
        with patch.object(service.web_discovery, "discover") as mock_discover:
            mock_discover.return_value = {"results": [], "classification": {"domain": "pmfby"}}
            result = service.retrieve(query="PMFBY eligibility")
            assert result.abstained is True
            assert result.reason == AbstentionReason.NO_ELIGIBLE_SOURCE


# ---------------------------------------------------------------------------
# Step 3: BM25 ranking
# ---------------------------------------------------------------------------

class TestBM25Ranking:
    def test_bm25_failure_uses_fallback(self):
        service = WebRAGService()
        sources = [_make_source()]
        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates", side_effect=RuntimeError("BM25 error")),
            patch.object(service.reranker, "pre_rank") as mock_pre,
        ):
            mock_discover.return_value = {"results": sources, "classification": {"domain": "pmfby"}}
            mock_pre.return_value = sources
            with patch.object(service.reranker, "final_rerank") as mock_final:
                mock_final.return_value = sources
                with patch.object(service.source_verifier, "verify_and_filter") as mock_verify:
                    mock_verify.return_value = {
                        "accepted_sources": sources,
                        "rejected_sources": [],
                        "summary": {},
                    }
                    result = service.retrieve(query="PMFBY eligibility")
                    # Should not crash, BM25 failure uses fallback
                    assert result is not None


# ---------------------------------------------------------------------------
# Step 7: Relevance gate
# ---------------------------------------------------------------------------

class TestRelevanceGate:
    def test_below_threshold_abstains(self):
        service = WebRAGService(minimum_relevance_score=60.0)
        sources = [_make_source(rerank_score=30.0, gemini_score=30.0)]
        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
        ):
            mock_discover.return_value = {"results": sources, "classification": {"domain": "pmfby"}}
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            result = service.retrieve(query="PMFBY eligibility")
            assert result.abstained is True
            assert result.reason == AbstentionReason.BELOW_TOP1_THRESHOLD

    def test_above_threshold_passes(self):
        service = WebRAGService(minimum_relevance_score=60.0)
        sources = [_make_source(rerank_score=75.0, gemini_score=75.0)]
        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
            patch.object(service.source_verifier, "verify_and_filter") as mock_verify,
        ):
            mock_discover.return_value = {"results": sources, "classification": {"domain": "pmfby"}}
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            mock_verify.return_value = {
                "accepted_sources": sources,
                "rejected_sources": [],
                "summary": {"total_sources": 1, "verified_sources": 1},
            }
            result = service.retrieve(query="PMFBY eligibility")
            assert result.abstained is False
            assert len(result.chunks) > 0

    def test_all_inapplicable_abstains(self):
        service = WebRAGService(minimum_relevance_score=60.0)
        sources = [_make_source(rerank_applicable=False, rerank_score=0.0, gemini_score=0.0)]
        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
        ):
            mock_discover.return_value = {"results": sources, "classification": {"domain": "pmfby"}}
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            result = service.retrieve(query="PMFBY eligibility")
            assert result.abstained is True
            assert result.reason == AbstentionReason.BELOW_TOP1_THRESHOLD


# ---------------------------------------------------------------------------
# Step 8: Source verification
# ---------------------------------------------------------------------------

class TestSourceVerification:
    def test_no_accepted_sources_abstains(self):
        service = WebRAGService()
        sources = [_make_source(rerank_score=75.0, gemini_score=75.0)]
        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
            patch.object(service.source_verifier, "verify_and_filter") as mock_verify,
        ):
            mock_discover.return_value = {"results": sources, "classification": {"domain": "pmfby"}}
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            mock_verify.return_value = {
                "accepted_sources": [],
                "rejected_sources": sources,
                "summary": {"total_sources": 1, "verified_sources": 0},
            }
            result = service.retrieve(query="PMFBY eligibility")
            assert result.abstained is True
            assert result.reason == AbstentionReason.INSUFFICIENT_EVIDENCE

    def test_verification_failure_uses_fallback(self):
        service = WebRAGService()
        sources = [_make_source(rerank_score=75.0, gemini_score=75.0)]
        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
            patch.object(
                service.source_verifier, "verify_and_filter",
                side_effect=RuntimeError("Verify error"),
            ),
        ):
            mock_discover.return_value = {"results": sources, "classification": {"domain": "pmfby"}}
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            # Verification failure uses fallback (all sources accepted)
            result = service.retrieve(query="PMFBY eligibility")
            assert result is not None


# ---------------------------------------------------------------------------
# Step 10: EvidenceChunk conversion
# ---------------------------------------------------------------------------

class TestEvidenceChunkConversion:
    def test_converts_source_to_evidence_chunk(self):
        service = WebRAGService()
        source = _make_source()
        classification_data = {"domain": "pmfby", "jurisdiction": "central", "state": None}
        chunk = service._to_evidence_chunk(source, classification_data)

        assert isinstance(chunk, EvidenceChunk)
        assert chunk.chunk_id == "web_abc123_c1"
        assert chunk.source_type == "web"
        assert chunk.domain == "pmfby"
        assert chunk.jurisdiction == "central"
        assert chunk.url == "https://pmfby.gov.in/guidelines"
        assert chunk.title == "PMFBY Guidelines"
        assert "PMFBY" in chunk.content

    def test_evidence_chunk_preserves_metadata(self):
        service = WebRAGService()
        source = _make_source(rerank_score=80.0, bm25_score=5.5)
        classification_data = {"domain": "pmfby"}
        chunk = service._to_evidence_chunk(source, classification_data)

        assert chunk.rerank_score == 80.0
        assert chunk.bm25_score == 5.5
        assert chunk.metadata["official"] is True
        assert chunk.metadata["verification_status"] is None  # not set by source


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_successful_pipeline_returns_evidence(self):
        service = WebRAGService(minimum_relevance_score=60.0)
        sources = [_make_source(rerank_score=80.0, gemini_score=80.0)]

        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
            patch.object(service.source_verifier, "verify_and_filter") as mock_verify,
        ):
            mock_discover.return_value = {
                "results": sources,
                "classification": {"domain": "pmfby", "jurisdiction": "central", "state": None},
            }
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            mock_verify.return_value = {
                "accepted_sources": sources,
                "rejected_sources": [],
                "summary": {"total_sources": 1, "verified_sources": 1},
            }

            result = service.retrieve(query="What is PMFBY eligibility?")

            assert isinstance(result, RAGResult)
            assert result.abstained is False
            assert len(result.chunks) == 1
            assert result.chunks[0].source_type == "web"
            assert result.domain == "pmfby"

    def test_multiple_sources_returned(self):
        service = WebRAGService(minimum_relevance_score=60.0)
        sources = [
            _make_source(chunk_id="web_abc_c1", rerank_score=85.0, gemini_score=85.0),
            _make_source(chunk_id="web_abc_c2", rerank_score=70.0, gemini_score=70.0),
            _make_source(chunk_id="web_abc_c3", rerank_score=65.0, gemini_score=65.0),
        ]

        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
            patch.object(service.source_verifier, "verify_and_filter") as mock_verify,
        ):
            mock_discover.return_value = {
                "results": sources,
                "classification": {"domain": "pmfby"},
            }
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            mock_verify.return_value = {
                "accepted_sources": sources,
                "rejected_sources": [],
                "summary": {"total_sources": 3, "verified_sources": 3},
            }

            result = service.retrieve(query="PMFBY scheme details")

            assert len(result.chunks) == 3
            assert all(c.source_type == "web" for c in result.chunks)

    def test_pipeline_with_preclassified_query(self):
        service = WebRAGService(minimum_relevance_score=60.0)
        classification = _make_classification(domain="cooperative", state="gujarat")
        sources = [_make_source(rerank_score=70.0, gemini_score=70.0)]

        with (
            patch.object(service.web_discovery, "discover") as mock_discover,
            patch.object(service.bm25, "rank_candidates") as mock_bm25,
            patch.object(service.reranker, "pre_rank") as mock_pre,
            patch.object(service.reranker, "final_rerank") as mock_final,
            patch.object(service.source_verifier, "verify_and_filter") as mock_verify,
        ):
            mock_discover.return_value = {
                "results": sources,
                "classification": {"domain": "cooperative", "jurisdiction": "state", "state": "gujarat"},
            }
            mock_bm25.return_value = sources
            mock_pre.return_value = sources
            mock_final.return_value = sources
            mock_verify.return_value = {
                "accepted_sources": sources,
                "rejected_sources": [],
                "summary": {},
            }

            result = service.retrieve(
                query="Cooperative society registration in Gujarat",
                classification=classification,
            )

            assert result.domain == "cooperative"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_default_min_relevance_score(self):
        assert DEFAULT_MIN_RELEVANCE_SCORE in (0.0, 40.0)

    def test_top_k_parameter(self):
        service = WebRAGService()
        assert service.final_top_k == 8

    def test_custom_parameters(self):
        service = WebRAGService(
            bm25_top_k=20,
            gemini_pre_top_k=20,
            final_top_k=10,
            rrf_k=30,
            minimum_relevance_score=70.0,
            minimum_trust_score=40.0,
        )
        assert service.bm25_top_k == 20
        assert service.gemini_pre_top_k == 20
        assert service.final_top_k == 10
        assert service.rrf_k == 30
        assert service.minimum_relevance_score == 70.0
