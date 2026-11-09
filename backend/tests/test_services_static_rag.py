"""Tests for StaticRAGService — static RAG pipeline encapsulation."""
from __future__ import annotations

from unittest.mock import patch


from app.config import Settings
from app.contracts import AbstentionReason, ConfidenceBand, RAGResult
from app.retrieval import RetrievedChunk
from app.services.static_rag import StaticRAGService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> Settings:
    """Create a Settings instance for testing."""
    defaults = {
        "groq_api_key": "test-groq-key",
        "gemini_api_key": "test-gemini-key",
        "jina_api_key": "test-jina-key",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test-key",
        "reranker_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_retrieved_chunk(
    chunk_id: str = "chunk-1",
    content: str = "Test content about PMFBY",
    domain: str = "pmfby",
    jurisdiction: str = "central",
    state: str | None = None,
    similarity: float = 0.60,
    title: str = "PMFBY Guidelines",
    section: str = "Overview",
    page: int = 1,
    document_id: str = "doc-1",
    source_url: str = "https://example.com/pmfby",
    source_file: str = "pmfby.pdf",
    stable_chunk_id: str = "stable-chunk-1",
) -> RetrievedChunk:
    """Create a RetrievedChunk for testing."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        stable_chunk_id=stable_chunk_id,
        document_id=document_id,
        title=title,
        page=page,
        page_start=page,
        page_end=page,
        section=section,
        subsection="",
        clause="",
        content=content,
        similarity=similarity,
        source_url=source_url,
        source_file=source_file,
        domain=domain,
        jurisdiction=jurisdiction,
        state=state,
    )


# ---------------------------------------------------------------------------
# Domain mapping
# ---------------------------------------------------------------------------

class TestDomainMapping:
    """Verify _DOMAIN_MAP correctly translates raw domain to retrieval domain."""

    def test_pacs_maps_to_pacs_governance(self):
        service = StaticRAGService(_make_settings())
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[]):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pacs",
                state=None,
            )
        assert result.domain == "pacs_governance"

    def test_finlit_maps_to_financial_inclusion(self):
        service = StaticRAGService(_make_settings())
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[]):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="finlit",
                state=None,
            )
        assert result.domain == "financial_inclusion"

    def test_pmfby_passes_through(self):
        service = StaticRAGService(_make_settings())
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[]):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
        assert result.domain == "pmfby"


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class TestRetrieval:
    """Verify retrieve_hybrid is called with correct arguments."""

    def test_retrieve_hybrid_called_with_correct_args(self):
        service = StaticRAGService(_make_settings())
        embedding = [0.1] * 768

        with patch("app.services.static_rag.get_supabase") as mock_db, \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[]) as mock_retrieve:
            service.retrieve(
                embedding=embedding,
                query="What is PMFBY?",
                domain="pmfby",
                state="gujarat",
                k=10,
            )
            mock_retrieve.assert_called_once_with(
                mock_db.return_value, embedding, "What is PMFBY?", "pmfby", "gujarat", k=10,
                as_of_date=None,
            )

    def test_default_k_without_reranker(self):
        service = StaticRAGService(_make_settings(reranker_enabled=False))
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[]) as mock_retrieve:
            service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            _, kwargs = mock_retrieve.call_args
            assert kwargs["k"] == 25

    def test_default_k_with_reranker(self):
        service = StaticRAGService(_make_settings(reranker_enabled=True))
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[]) as mock_retrieve:
            service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            _, kwargs = mock_retrieve.call_args
            assert kwargs["k"] == 25

    def test_retrieval_failure_returns_abstained(self):
        service = StaticRAGService(_make_settings())
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", side_effect=Exception("DB error")):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
        assert result.abstained is True
        assert result.reason == AbstentionReason.PROVIDER_UNAVAILABLE
        assert result.band == ConfidenceBand.LOW
        assert result.chunks == []


# ---------------------------------------------------------------------------
# Evidence chunk conversion
# ---------------------------------------------------------------------------

class TestEvidenceChunkConversion:
    """Verify RetrievedChunk -> EvidenceChunk conversion."""

    def test_basic_conversion(self):
        chunk = _make_retrieved_chunk(
            chunk_id="test-uuid",
            content="PMFBY premium details",
            domain="pmfby",
            jurisdiction="central",
            similarity=0.75,
            title="PMFBY Guidelines",
            section="Premium Rate",
            page=47,
            source_url="https://example.com/pmfby",
            source_file="pmfby.pdf",
            stable_chunk_id="stable-test-1",
            document_id="doc-123",
        )
        service = StaticRAGService(_make_settings())

        _result = service.retrieve(
            embedding=[0.1] * 768,
            query="PMFBY premium",
            domain="pmfby",
            state=None,
        )

        # Since retrieve_hybrid is mocked, we need to test _to_evidence_chunk directly
        evidence = StaticRAGService._to_evidence_chunk(chunk, "pmfby")
        assert evidence.chunk_id == "test-uuid"
        assert evidence.content == "PMFBY premium details"
        assert evidence.source_type == "static"
        assert evidence.title == "PMFBY Guidelines"
        assert evidence.url == "https://example.com/pmfby"
        assert evidence.page == 47
        assert evidence.section == "Premium Rate"
        assert evidence.domain == "pmfby"
        assert evidence.jurisdiction == "central"
        assert evidence.state is None
        assert evidence.dense_score == 0.75
        assert evidence.metadata["stable_chunk_id"] == "stable-test-1"
        assert evidence.metadata["document_id"] == "doc-123"
        assert evidence.metadata["source_file"] == "pmfby.pdf"

    def test_state_level_chunk_conversion(self):
        chunk = _make_retrieved_chunk(
            jurisdiction="state",
            state="gujarat",
            domain="pacs_governance",
        )
        evidence = StaticRAGService._to_evidence_chunk(chunk, "pacs_governance")
        assert evidence.jurisdiction == "state"
        assert evidence.state == "gujarat"

    def test_domain_fallback_to_argument(self):
        chunk = _make_retrieved_chunk(domain="")
        evidence = StaticRAGService._to_evidence_chunk(chunk, "pmfby")
        assert evidence.domain == "pmfby"


# ---------------------------------------------------------------------------
# Reranker integration
# ---------------------------------------------------------------------------

class TestRerankerIntegration:
    """Verify reranker is applied when enabled."""

    def test_reranker_called_when_enabled(self):
        service = StaticRAGService(_make_settings(reranker_enabled=True))
        chunks = [
            _make_retrieved_chunk(chunk_id="c1", similarity=0.6),
            _make_retrieved_chunk(chunk_id="c2", similarity=0.7),
            _make_retrieved_chunk(chunk_id="c3", similarity=0.5),
        ]
        reranked = [
            {"chunk_id": "c2", "reranker_score": 0.9},
            {"chunk_id": "c1", "reranker_score": 0.8},
            {"chunk_id": "c3", "reranker_score": 0.7},
        ]

        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=chunks), \
             patch("app.services.static_rag.JinaReranker") as MockReranker:
            MockReranker.return_value.rerank.return_value = reranked
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            MockReranker.return_value.rerank.assert_called_once()
            # Order should follow reranker output
            assert result.chunks[0].chunk_id == "c2"
            assert result.chunks[1].chunk_id == "c1"
            assert result.chunks[2].chunk_id == "c3"

    def test_reranker_skipped_when_disabled(self):
        service = StaticRAGService(_make_settings(reranker_enabled=False))
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[
                 _make_retrieved_chunk(chunk_id="c1"),
             ]), \
             patch("app.services.static_rag.JinaReranker") as MockReranker:
            service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            MockReranker.assert_not_called()

    def test_reranker_failure_returns_original_chunks(self):
        service = StaticRAGService(_make_settings(reranker_enabled=True))
        chunks = [
            _make_retrieved_chunk(chunk_id="c1"),
            _make_retrieved_chunk(chunk_id="c2"),
        ]

        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=chunks), \
             patch("app.services.static_rag.JinaReranker") as MockReranker:
            MockReranker.return_value.rerank.side_effect = Exception("API error")
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            # Should still return chunks (original order)
            assert len(result.chunks) == 2


# ---------------------------------------------------------------------------
# Evidence gate integration
# ---------------------------------------------------------------------------

class TestEvidenceGateIntegration:
    """Verify evidence_gate is called and its results propagate."""

    def test_gate_passes_with_good_chunks(self):
        service = StaticRAGService(_make_settings())
        chunks = [
            _make_retrieved_chunk(chunk_id="c1", similarity=0.80, jurisdiction="central"),
            _make_retrieved_chunk(chunk_id="c2", similarity=0.60, jurisdiction="central"),
            _make_retrieved_chunk(chunk_id="c3", similarity=0.50, jurisdiction="central"),
        ]

        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=chunks), \
             patch("app.services.static_rag.evidence_gate", return_value=(False, None, ConfidenceBand.HIGH)) as mock_gate:
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            mock_gate.assert_called_once()
            assert result.abstained is False
            assert result.reason is None
            assert result.band == ConfidenceBand.HIGH

    def test_gate_abstains_on_domain_mismatch(self):
        service = StaticRAGService(_make_settings())
        chunks = [_make_retrieved_chunk(domain="wrong_domain")]

        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=chunks), \
             patch("app.services.static_rag.evidence_gate",
                    return_value=(True, AbstentionReason.DOMAIN_MISMATCH, ConfidenceBand.LOW)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            assert result.abstained is True
            assert result.reason == AbstentionReason.DOMAIN_MISMATCH

    def test_gate_failure_returns_abstained(self):
        service = StaticRAGService(_make_settings())
        chunks = [_make_retrieved_chunk()]

        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=chunks), \
             patch("app.services.static_rag.evidence_gate", side_effect=Exception("gate error")):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            assert result.abstained is True
            assert result.reason == AbstentionReason.CITATION_FAILURE


# ---------------------------------------------------------------------------
# RAGResult structure
# ---------------------------------------------------------------------------

class TestRAGResultStructure:
    """Verify RAGResult is correctly populated."""

    def test_empty_retrieval_returns_empty_result(self):
        service = StaticRAGService(_make_settings())
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[]), \
             patch("app.services.static_rag.evidence_gate",
                    return_value=(True, AbstentionReason.NO_ELIGIBLE_SOURCE, ConfidenceBand.LOW)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
        assert isinstance(result, RAGResult)
        assert result.chunks == []
        assert result.abstained is True
        assert result.reason == AbstentionReason.NO_ELIGIBLE_SOURCE
        assert result.band == ConfidenceBand.LOW
        assert result.domain == "pmfby"

    def test_result_preserves_metadata(self):
        service = StaticRAGService(_make_settings())
        chunk = _make_retrieved_chunk(
            chunk_id="meta-test",
            content="Test content",
            domain="pmfby",
            similarity=0.65,
            title="Test Title",
            section="Test Section",
            page=10,
        )

        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid", return_value=[chunk]), \
             patch("app.services.static_rag.evidence_gate",
                    return_value=(False, None, ConfidenceBand.MEDIUM)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state="gujarat",
            )
        assert len(result.chunks) == 1
        assert result.chunks[0].chunk_id == "meta-test"
        assert result.chunks[0].source_type == "static"
        assert result.chunks[0].title == "Test Title"
        assert result.domain == "pmfby"
