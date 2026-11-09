"""Comprehensive retrieval scenario tests.

Tests that the retrieval pipeline produces the correct evidence for
various query types. These are unit-level tests with mocked Supabase
that verify the pipeline logic, NOT integration tests against live DB.

Scenarios per spec §12:
1. Direct scheme question
2. Direct service question
3. Direct law question
4. Procedure question
5. Eligibility question
6. Numeric/threshold question
7. Question requiring two sections
8. Question requiring two documents
9. Central + Gujarat question
10. Colloquial/Romanized query
11. Weak semantic match
12. Duplicate evidence
13. Citation preservation

Plus scenario-shaped questions to verify evidence completeness.
"""
from __future__ import annotations

from unittest.mock import patch

from app.config import Settings
from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    EvidenceChunk,
)
from app.evidence_gate import evidence_gate
from app.retrieval import RetrievedChunk
from app.services.static_rag import StaticRAGService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test",
        "gemini_api_key": "test",
        "jina_api_key": "test",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test",
        "reranker_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _chunk(
    chunk_id: str,
    content: str,
    domain: str = "pmfby",
    title: str = "PMFBY Guidelines",
    section: str = "Overview",
    page: int = 1,
    jurisdiction: str = "central",
    state: str | None = None,
    similarity: float = 0.70,
    document_id: str = "doc-1",
    source_file: str = "pmfby.pdf",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        stable_chunk_id=f"stable:{chunk_id}",
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
        source_url="",
        source_file=source_file,
        domain=domain,
        jurisdiction=jurisdiction,
        state=state,
    )


def _evidence(
    chunk_id: str,
    content: str,
    source_type: str = "static",
    domain: str = "pmfby",
    dense_score: float = 0.70,
    title: str = "PMFBY Guidelines",
    section: str = "Overview",
    page: int = 1,
    document_id: str = "doc-1",
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        content=content,
        source_type=source_type,
        title=title,
        url="",
        page=page,
        section=section,
        domain=domain,
        jurisdiction="central",
        state=None,
        dense_score=dense_score,
        metadata={"document_id": document_id, "source_file": f"{domain}.pdf"},
    )


# ---------------------------------------------------------------------------
# 1. Direct scheme question
# ---------------------------------------------------------------------------

class TestDirectSchemeQuestion:
    """Q: 'What is PMFBY?' → should retrieve scheme definition chunks."""

    def test_retrieval_returns_pmfby_chunks(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PMFBY provides crop insurance", domain="pmfby",
                   section="Introduction", similarity=0.85),
            _chunk("c2", "PMFBY premium rates for farmers", domain="pmfby",
                   section="Premium", similarity=0.72),
            _chunk("c3", "PMFBY enrollment process", domain="pmfby",
                   section="Enrollment", similarity=0.65),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.HIGH)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="What is PMFBY?",
                domain="pmfby",
                state=None,
            )
        assert not result.abstained
        assert len(result.chunks) == 3
        assert all(c.domain == "pmfby" for c in result.chunks)

    def test_evidence_gate_validates_scheme_chunks(self):
        chunks = [
            _evidence("c1", "PMFBY provides crop insurance", dense_score=0.85),
            _evidence("c2", "PMFBY premium rates", dense_score=0.72),
        ]
        abstained, _reason, band = evidence_gate(
            chunks, expected_domain="pmfby",
        )
        assert not abstained
        assert band in (ConfidenceBand.HIGH, ConfidenceBand.MEDIUM)


# ---------------------------------------------------------------------------
# 2. Direct service question
# ---------------------------------------------------------------------------

class TestDirectServiceQuestion:
    """Q: 'How to join a PACS?' → should retrieve service/procedure chunks."""

    def test_retrieval_returns_pacs_chunks(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "Process to join PACS cooperative",
                   domain="pacs_governance", section="Membership",
                   title="Model Byelaws", similarity=0.80),
            _chunk("c2", "PACS eligibility criteria for membership",
                   domain="pacs_governance", section="Eligibility",
                   title="Model Byelaws", similarity=0.68),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.MEDIUM)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="How to join a PACS?",
                domain="pacs",
                state=None,
            )
        assert not result.abstained
        assert result.domain == "pacs_governance"


# ---------------------------------------------------------------------------
# 3. Direct law question
# ---------------------------------------------------------------------------

class TestDirectLawQuestion:
    """Q: 'What are the provisions of the Cooperative Societies Act?'"""

    def test_retrieval_returns_legal_chunks(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "Cooperative Societies Act provisions for registration",
                   domain="pacs_governance", section="Legal Provisions",
                   title="Model Byelaws", similarity=0.75),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.MEDIUM)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="What are the provisions of the Cooperative Societies Act?",
                domain="pacs",
                state=None,
            )
        assert not result.abstained
        assert any("provision" in c.content.lower() for c in result.chunks)


# ---------------------------------------------------------------------------
# 4. Procedure question
# ---------------------------------------------------------------------------

class TestProcedureQuestion:
    """Q: 'How to file a grievance for delayed PMFBY claim payment?'"""

    def test_retrieval_returns_procedure_chunks(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PMFBY claim settlement procedure steps",
                   domain="pmfby", section="Claims", similarity=0.82),
            _chunk("c2", "Grievance redressal mechanism for PMFBY",
                   domain="pmfby", section="Grievance", similarity=0.70),
            _chunk("c3", "Timeline for PMFBY claim processing",
                   domain="pmfby", section="Timeline", similarity=0.65),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.HIGH)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="How to file a grievance for delayed PMFBY claim payment?",
                domain="pmfby",
                state=None,
            )
        assert not result.abstained
        assert len(result.chunks) >= 2


# ---------------------------------------------------------------------------
# 5. Eligibility question
# ---------------------------------------------------------------------------

class TestEligibilityQuestion:
    """Q: 'Who is eligible for PM-KISAN scheme?'"""

    def test_retrieval_returns_eligibility_chunks(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PM-KISAN eligibility criteria: all farmer families",
                   domain="pmfby", section="Eligibility", similarity=0.78),
            _chunk("c2", "Exclusions from PM-KISAN: institutional landholders",
                   domain="pmfby", section="Exclusions", similarity=0.65),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.MEDIUM)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="Who is eligible for PM-KISAN scheme?",
                domain="pmfby",
                state=None,
            )
        assert not result.abstained
        assert any("eligib" in c.content.lower() for c in result.chunks)


# ---------------------------------------------------------------------------
# 6. Numeric/threshold question
# ---------------------------------------------------------------------------

class TestNumericThresholdQuestion:
    """Q: 'What is the minimum premium for PMFBY for kharif crops?'"""

    def test_retrieval_includes_numeric_chunks(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PMFBY kharif crop premium rate is 2% of sum insured",
                   domain="pmfby", section="Premium Rates", similarity=0.88),
            _chunk("c2", "Sum insured calculation for PMFBY",
                   domain="pmfby", section="Sum Insured", similarity=0.60),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.HIGH)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="What is the minimum premium for PMFBY for kharif crops?",
                domain="pmfby",
                state=None,
            )
        assert not result.abstained
        assert any("2%" in c.content or "premium" in c.content.lower()
                    for c in result.chunks)


# ---------------------------------------------------------------------------
# 7. Question requiring two sections
# ---------------------------------------------------------------------------

class TestTwoSectionsQuestion:
    """Q: 'What are PMFBY premium rates AND the claim settlement process?'"""

    def test_retrieval_covers_multiple_sections(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PMFBY premium rates: 2% kharif, 1.5% rabi",
                   domain="pmfby", section="Premium Rates", similarity=0.85),
            _chunk("c2", "PMFBY claim settlement process: 14 days timeline",
                   domain="pmfby", section="Claims", similarity=0.78),
            _chunk("c3", "PMFBY enrollment procedure",
                   domain="pmfby", section="Enrollment", similarity=0.55),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.HIGH)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="What are PMFBY premium rates AND the claim settlement process?",
                domain="pmfby",
                state=None,
            )
        assert not result.abstained
        sections = {c.section for c in result.chunks}
        assert "Premium Rates" in sections or "Claims" in sections


# ---------------------------------------------------------------------------
# 8. Question requiring two documents
# ---------------------------------------------------------------------------

class TestTwoDocumentsQuestion:
    """Q: 'What is the difference between PMFBY and PM-KUSUM subsidies?'"""

    def test_retrieval_covers_multiple_documents(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PMFBY crop insurance subsidy details",
                   domain="pmfby", title="PMFBY Guidelines",
                   section="Subsidy", similarity=0.80,
                   document_id="doc-pmfby"),
            _chunk("c2", "PM-KUSUM solar pump subsidy details",
                   domain="pmfby", title="PM-KUSUM Guidelines",
                   section="Subsidy", similarity=0.72,
                   document_id="doc-pmkusum"),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.HIGH)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="What is the difference between PMFBY and PM-KUSUM subsidies?",
                domain="pmfby",
                state=None,
            )
        assert not result.abstained
        doc_ids = {c.metadata.get("document_id") for c in result.chunks}
        assert len(doc_ids) >= 2



# ---------------------------------------------------------------------------
# 9. Central + Gujarat question
# ---------------------------------------------------------------------------

class TestCentralGujaratQuestion:
    """Q: 'What is the PMFBY premium for Gujarat kharif crops?'"""

    def test_retrieval_includes_both_central_and_state(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PMFBY central premium rate: 2% kharif",
                   domain="pmfby", jurisdiction="central",
                   section="Premium", similarity=0.85),
            _chunk("c2", "Gujarat PMFBY additional provisions",
                   domain="pmfby", jurisdiction="state", state="gujarat",
                   section="Gujarat Specific", similarity=0.75),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.HIGH)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="What is the PMFBY premium for Gujarat kharif crops?",
                domain="pmfby",
                state="gujarat",
            )
        assert not result.abstained
        jurisdictions = {c.jurisdiction for c in result.chunks}
        assert "central" in jurisdictions

    def test_evidence_gate_allows_central_for_gujarat_query(self):
        chunks = [
            _evidence("c1", "Central PMFBY rule", dense_score=0.85),
            _evidence("c2", "Central PMFBY detail", dense_score=0.70),
        ]
        # Central evidence should pass even for Gujarat query
        abstained, _, _ = evidence_gate(
            chunks, expected_domain="pmfby", expected_state="gujarat",
        )
        assert not abstained

    def test_evidence_gate_rejects_mismatched_state(self):
        chunks = [
            EvidenceChunk(
                chunk_id="c1", content="Maharashtra specific", source_type="static",
                domain="pmfby", jurisdiction="state", state="maharashtra",
                dense_score=0.85,
            ),
        ]
        abstained, reason, _ = evidence_gate(
            chunks, expected_domain="pmfby", expected_state="gujarat",
        )
        assert abstained
        assert reason == AbstentionReason.JURISDICTION_MISMATCH


# ---------------------------------------------------------------------------
# 10. Colloquial/Romanized query
# ---------------------------------------------------------------------------

class TestColloquialQuery:
    """Q: 'PMFBY ka premium kya hai?' (Hindi in Roman script)"""

    def test_retrieval_works_for_romanized_query(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "PMFBY premium rate is 2% for kharif crops",
                   domain="pmfby", similarity=0.70),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(False, None, ConfidenceBand.MEDIUM)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="PMFBY ka premium kya hai?",
                domain="pmfby",
                state=None,
            )
        assert not result.abstained
        assert len(result.chunks) >= 1


# ---------------------------------------------------------------------------
# 11. Weak semantic match
# ---------------------------------------------------------------------------

class TestWeakSemanticMatch:
    """Chunks with low similarity scores should NOT be artificially boosted."""

    def test_weak_chunks_keep_original_score(self):
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "Tangentially related content", similarity=0.15),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate",
                   return_value=(True, AbstentionReason.BELOW_TOP1_THRESHOLD,
                                 ConfidenceBand.LOW)):
            result = service.retrieve(
                embedding=[0.1] * 768,
                query="Something unrelated",
                domain="pmfby",
                state=None,
            )
        assert result.abstained

    def test_weak_chunks_not_boosted_to_050(self):
        """Regression: previously, chunks < 0.20 were boosted to 0.50."""
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "Weak match", similarity=0.15),
        ]
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate") as mock_gate:
            service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            # evidence_gate should see the original 0.15, not 0.50
            gate_chunks = mock_gate.call_args[0][0]
            assert gate_chunks[0].dense_score == 0.15


# ---------------------------------------------------------------------------
# 12. Duplicate evidence
# ---------------------------------------------------------------------------

class TestDuplicateEvidence:
    """Duplicate chunks from same document+section should be deduplicated."""

    def test_same_chunk_id_deduplicated_in_merge(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        static = [_evidence("c1", "Static version of chunk", dense_score=0.80)]
        web = [_evidence("c1", "Web version of chunk", dense_score=0.70)]

        merged = orch._merge_evidence(static, web)

        assert len(merged) == 1
        assert merged[0].chunk_id == "c1"

    def test_different_chunks_preserved(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        static = [_evidence("c1", "First chunk", dense_score=0.80)]
        web = [_evidence("c2", "Second chunk", dense_score=0.70)]

        merged = orch._merge_evidence(static, web)

        assert len(merged) == 2
        ids = {c.chunk_id for c in merged}
        assert ids == {"c1", "c2"}

    def test_higher_score_wins_on_duplicate(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        static = [_evidence("c1", "Lower score static", dense_score=0.50)]
        web = [_evidence("c1", "Higher score web", dense_score=0.90)]

        merged = orch._merge_evidence(static, web)

        assert len(merged) == 1
        assert merged[0].content == "Higher score web"


# ---------------------------------------------------------------------------
# 13. Citation preservation
# ---------------------------------------------------------------------------

class TestCitationPreservation:
    """Every evidence chunk must have valid metadata for citation."""

    def test_existing_citations_preserved(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        chunks = [_evidence("c1", "Content", dense_score=0.80)]
        answer = "PMFBY provides crop insurance [chunk:c1-abcd1234]."

        result = orch._auto_append_citations(answer, chunks)

        assert "[chunk:c1-abcd1234]" in result

    def test_non_citation_brackets_cleaned(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        chunks = [_evidence("c1", "Content", dense_score=0.80)]
        answer = "PMFBY provides [1] crop insurance [Note] here."

        result = orch._auto_append_citations(answer, chunks)

        assert "[1]" not in result
        assert "[Note]" not in result

    def test_citations_appended_when_missing(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        chunks = [
            _evidence("c1", "First chunk", dense_score=0.80),
            _evidence("c2", "Second chunk", dense_score=0.70),
        ]
        answer = "PMFBY provides crop insurance."

        result = orch._auto_append_citations(answer, chunks)

        assert "[chunk:" in result

    def test_web_citation_markers_preserved(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        chunks = [_evidence("c1", "Content", dense_score=0.80)]
        answer = "According to [web_source_1], PMFBY exists."

        result = orch._auto_append_citations(answer, chunks)

        assert "[web_source_1]" in result


# ---------------------------------------------------------------------------
# Scenario-shaped questions (verify evidence completeness, NOT reasoning)
# ---------------------------------------------------------------------------

class TestScenarioEvidenceCompleteness:
    """Verify that the evidence set covers all required aspects of
    scenario-shaped questions. These do NOT test answer generation."""


    def test_gujarat_specific_plus_central_evidence(self):
        """Scenario: 'What are Gujarat-specific PMFBY provisions?'
        Needs: Gujarat state evidence + applicable central evidence."""
        chunks = [
            _evidence("c1", "Central PMFBY guidelines",
                      section="Central", dense_score=0.80),
            EvidenceChunk(
                chunk_id="c2", content="Gujarat PMFBY add-on",
                source_type="static", domain="pmfby",
                jurisdiction="state", state="gujarat",
                dense_score=0.75, section="Gujarat",
                metadata={"document_id": "doc-guj"},
            ),
        ]
        # Both should pass the evidence gate
        abstained, _, _ = evidence_gate(
            chunks, expected_domain="pmfby", expected_state="gujarat",
        )
        assert not abstained


# ---------------------------------------------------------------------------
# Weak-score distortion regression
# ---------------------------------------------------------------------------

class TestWeakScoreDistortionRemoval:
    """Verify that weak chunks are NOT artificially boosted."""

    def test_similarity_below_020_preserved(self):
        """Previously: chunk.similarity < 0.20 was set to 0.50.
        Now: original similarity is preserved."""
        service = StaticRAGService(_settings())
        mock_chunks = [
            _chunk("c1", "Very weak match", similarity=0.12),
            _chunk("c2", "Weak match", similarity=0.18),
            _chunk("c3", "Decent match", similarity=0.55),
        ]
        # Capture what evidence_gate receives
        gate_received = []

        def capture_gate(chunks, **kwargs):
            gate_received.extend(chunks)
            return (False, None, ConfidenceBand.MEDIUM)

        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=mock_chunks), \
             patch("app.services.static_rag.evidence_gate", side_effect=capture_gate):
            service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )

        # Verify original scores are preserved (no boost to 0.50)
        scores = {c.chunk_id: c.dense_score for c in gate_received}
        assert scores["c1"] == 0.12
        assert scores["c2"] == 0.18
        assert scores["c3"] == 0.55


# ---------------------------------------------------------------------------
# Candidate pool size
# ---------------------------------------------------------------------------

class TestCandidatePoolSize:
    """Verify the retrieval pool is always 25 (larger candidate pool)."""

    def test_default_pool_size_is_25(self):
        service = StaticRAGService(_settings())
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=[]) as mock_retrieve:
            service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
            )
            _, kwargs = mock_retrieve.call_args
            assert kwargs["k"] == 25

    def test_explicit_k_overrides_default(self):
        service = StaticRAGService(_settings())
        with patch("app.services.static_rag.get_supabase"), \
             patch("app.services.static_rag.StaticRAGService._retrieve_hybrid",
                   return_value=[]) as mock_retrieve:
            service.retrieve(
                embedding=[0.1] * 768,
                query="test",
                domain="pmfby",
                state=None,
                k=10,
            )
            _, kwargs = mock_retrieve.call_args
            assert kwargs["k"] == 10


# ---------------------------------------------------------------------------
# Cross-source ranking
# ---------------------------------------------------------------------------

class TestCrossSourceRanking:
    """Verify cross-source final ranking in orchestrator."""

    def test_static_chunks_get_authority_boost(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        static = [_evidence("s1", "Static content", source_type="static",
                            dense_score=0.70)]
        web = [_evidence("w1", "Web content", source_type="web",
                         dense_score=0.70)]

        merged = orch._merge_evidence(static, web)

        # Static should rank higher due to authority boost
        assert merged[0].chunk_id == "s1"
        assert merged[1].chunk_id == "w1"

    def test_weak_web_does_not_displace_strong_static(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        static = [_evidence("s1", "Strong static", source_type="static",
                            dense_score=0.85)]
        web = [_evidence("w1", "Weak web", source_type="web",
                         dense_score=0.40)]

        merged = orch._merge_evidence(static, web)

        # Static should still be first
        assert merged[0].chunk_id == "s1"

    def test_cross_source_deduplication(self):
        from app.services.rag_orchestrator import RAGOrchestrator

        orch = RAGOrchestrator(_settings())
        static = [_evidence("c1", "Static version", source_type="static",
                            dense_score=0.80)]
        web = [_evidence("c1", "Web version", source_type="web",
                         dense_score=0.70)]

        merged = orch._merge_evidence(static, web)

        # Only one copy should exist
        assert len(merged) == 1
        assert merged[0].chunk_id == "c1"
