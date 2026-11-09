# RAG Architecture Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 1053-line monolithic chat.py with modular service classes (StaticRAGService, WebRAGService, RAGOrchestrator) that share a unified EvidenceChunk format and evidence gate, while keeping the dual parallel pipeline architecture.

**Architecture:** Three new service classes in `backend/app/services/` encapsulate all RAG logic. Chat route becomes thin (~200 lines) delegating to RAGOrchestrator. Web RAG pipeline follows eGovAssistant's proven 10-step architecture. Both pipelines emit EvidenceChunk objects validated by a single unified evidence gate.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Supabase pgvector, httpx, Tavily/Firecrawl, Gemini API, Groq API

## Global Constraints

- Python: type hints everywhere, Pydantic models for all request/response bodies, no bare `except`
- Every external provider call goes through an adapter with explicit timeout and fallback
- Never put API keys in frontend code or expose via `NEXT_PUBLIC_*`
- Structured logs. Never log API keys, auth tokens, or full grievance PII
- Never fabricate eligibility, amounts, dates, deadlines, legal clauses, or contacts
- Every citation must map to a chunk ID that was actually retrieved in that request
- The LLM is NEVER the source of truth — every factual answer must be grounded in retrieved chunks

---

## Task 1: Add Unified EvidenceChunk, RAGResult, RAGResponse to contracts.py

**Files:**
- Modify: `backend/app/contracts.py`
- Test: `backend/tests/test_contracts_evidence_chunk.py`

**Interfaces:**
- Consumes: existing `AbstentionReason`, `ConfidenceBand` from contracts.py
- Produces: `EvidenceChunk`, `RAGResult`, `RAGResponse` models used by all services

- [ ] **Step 1: Write failing tests for new models**

```python
# backend/tests/test_contracts_evidence_chunk.py
"""Tests for unified EvidenceChunk, RAGResult, RAGResponse models."""
from app.contracts import EvidenceChunk, RAGResult, RAGResponse, AbstentionReason, ConfidenceBand


def test_evidence_chunk_static():
    chunk = EvidenceChunk(
        chunk_id="pmfby_00012",
        content="PMFBY premium rates vary by crop...",
        source_type="static",
        title="PMFBY Operational Guidelines",
        url="https://example.com/pmfby.pdf",
        page=47,
        section="Variation in Premium Rate",
        domain="pmfby",
        jurisdiction="central",
        state=None,
        dense_score=0.85,
        bm25_score=12.5,
        rerank_score=None,
        trust_score=None,
        metadata={},
    )
    assert chunk.chunk_id == "pmfby_00012"
    assert chunk.source_type == "static"
    assert chunk.page == 47


def test_evidence_chunk_web():
    chunk = EvidenceChunk(
        chunk_id="web_abc123",
        content="The PMFBY scheme provides crop insurance...",
        source_type="web",
        title="PMFBY Overview - Gov.in",
        url="https://pmfby.gov.in/overview",
        page=None,
        section=None,
        domain="pmfby",
        jurisdiction="central",
        state=None,
        dense_score=0.72,
        bm25_score=None,
        rerank_score=85.0,
        trust_score=90.0,
        metadata={"source_domain": "gov.in"},
    )
    assert chunk.source_type == "web"
    assert chunk.trust_score == 90.0


def test_rag_result_abstained():
    result = RAGResult(
        chunks=[],
        abstained=True,
        reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
        band=None,
        domain="pmfby",
        metadata={},
    )
    assert result.abstained is True
    assert result.reason == AbstentionReason.INSUFFICIENT_EVIDENCE


def test_rag_result_success():
    chunk = EvidenceChunk(
        chunk_id="test_001", content="test", source_type="static",
        title="Test", url=None, page=1, section="s1",
        domain="pmfby", jurisdiction="central", state=None,
        dense_score=0.8, bm25_score=None, rerank_score=None,
        trust_score=None, metadata={},
    )
    result = RAGResult(
        chunks=[chunk], abstained=False, reason=None,
        band=ConfidenceBand.HIGH, domain="pmfby", metadata={},
    )
    assert result.abstained is False
    assert len(result.chunks) == 1


def test_rag_response():
    resp = RAGResponse(
        answer="PMFBY premium rates vary by crop...",
        language="en",
        domain="pmfby",
        confidence=0.85,
        confidence_level="high",
        citations=[{"chunk_id": "pmfby_00012", "title": "PMFBY Guidelines"}],
        abstained=False,
        speech_text="PMFBY premium rates vary by crop...",
        speech_segments=[],
        follow_up_question=None,
        mode="dual_rag",
        conversation_id="session_123",
    )
    assert resp.answer.startswith("PMFBY")
    assert resp.mode == "dual_rag"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_contracts_evidence_chunk.py -v`
Expected: FAIL — `EvidenceChunk`, `RAGResult`, `RAGResponse` not defined

- [ ] **Step 3: Add models to contracts.py**

```python
# Add to end of backend/app/contracts.py

class EvidenceChunk(BaseModel):
    """Unified evidence chunk from any pipeline (static or web)."""
    chunk_id: str
    content: str
    source_type: str  # "static" | "web"
    title: str
    url: str | None = None
    page: int | None = None
    section: str | None = None
    domain: str
    jurisdiction: str
    state: str | None = None
    dense_score: float = 0.0
    bm25_score: float | None = None
    rerank_score: float | None = None
    trust_score: float | None = None
    metadata: dict = Field(default_factory=dict)


class RAGResult(BaseModel):
    """Return type from StaticRAGService and WebRAGService."""
    chunks: list[EvidenceChunk]
    abstained: bool
    reason: AbstentionReason | None = None
    band: ConfidenceBand | None = None
    domain: str
    metadata: dict = Field(default_factory=dict)


class RAGResponse(BaseModel):
    """Return type from RAGOrchestrator — the final chat response."""
    answer: str
    language: str
    domain: str
    confidence: float
    confidence_level: str
    citations: list[dict]
    abstained: bool
    speech_text: str
    speech_segments: list[dict]
    follow_up_question: str | None = None
    mode: str
    conversation_id: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_contracts_evidence_chunk.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts.py backend/tests/test_contracts_evidence_chunk.py
git commit -m "feat: add EvidenceChunk, RAGResult, RAGResponse models to contracts"
```

---

## Task 2: Refactor evidence_gate.py to accept EvidenceChunk

**Files:**
- Modify: `backend/app/evidence_gate.py`
- Test: `backend/tests/test_evidence_gate_unified.py`

**Interfaces:**
- Consumes: `EvidenceChunk`, `AbstentionReason`, `ConfidenceBand` from Task 1
- Produces: `evidence_gate()` function used by both StaticRAGService and WebRAGService

- [ ] **Step 1: Write failing tests for unified evidence gate**

```python
# backend/tests/test_evidence_gate_unified.py
"""Tests for unified evidence gate accepting EvidenceChunk list."""
from app.contracts import EvidenceChunk, AbstentionReason
from app.evidence_gate import evidence_gate


def _make_chunk(chunk_id: str, domain: str = "pmfby", jurisdiction: str = "central",
                state: str | None = None, dense_score: float = 0.8) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id, content=f"content for {chunk_id}", source_type="static",
        title="Test", url=None, page=1, section="s1", domain=domain,
        jurisdiction=jurisdiction, state=state, dense_score=dense_score,
        bm25_score=None, rerank_score=None, trust_score=None, metadata={},
    )


def test_gate_passes_with_enough_chunks():
    chunks = [_make_chunk(f"chunk_{i}") for i in range(3)]
    abstained, reason, band = evidence_gate(chunks, expected_domain="pmfby", expected_state=None)
    assert abstained is False
    assert reason is None
    assert band is not None


def test_gate_abstains_on_empty():
    abstained, reason, band = evidence_gate([], expected_domain="pmfby", expected_state=None)
    assert abstained is True
    assert reason == AbstentionReason.INSUFFICIENT_EVIDENCE


def test_gate_abstains_on_wrong_domain():
    chunks = [_make_chunk(f"chunk_{i}", domain="agriculture") for i in range(3)]
    abstained, reason, band = evidence_gate(chunks, expected_domain="pmfby", expected_state=None)
    assert abstained is True
    assert reason == AbstentionReason.DOMAIN_MISMATCH


def test_gate_passes_web_chunks():
    chunks = [
        EvidenceChunk(
            chunk_id="web_001", content="web content", source_type="web",
            title="Web Source", url="https://example.com", page=None, section=None,
            domain="pmfby", jurisdiction="central", state=None, dense_score=0.7,
            bm25_score=None, rerank_score=85.0, trust_score=90.0, metadata={},
        )
        for _ in range(2)
    ]
    abstained, reason, band = evidence_gate(chunks, expected_domain="pmfby", expected_state=None)
    assert abstained is False


def test_gate混合_static_and_web():
    static_chunks = [_make_chunk(f"static_{i}") for i in range(2)]
    web_chunks = [
        EvidenceChunk(
            chunk_id=f"web_{i}", content="web content", source_type="web",
            title="Web", url="https://example.com", page=None, section=None,
            domain="pmfby", jurisdiction="central", state=None, dense_score=0.6,
            bm25_score=None, rerank_score=80.0, trust_score=85.0, metadata={},
        )
        for i in range(2)
    ]
    all_chunks = static_chunks + web_chunks
    abstained, reason, band = evidence_gate(all_chunks, expected_domain="pmfby", expected_state=None)
    assert abstained is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_evidence_gate_unified.py -v`
Expected: FAIL — `evidence_gate` doesn't accept `EvidenceChunk` list

- [ ] **Step 3: Add `evidence_gate` function to evidence_gate.py**

Add this function to `backend/app/evidence_gate.py` (keep existing `evidence_gate_v2` for backward compatibility during migration):

```python
def evidence_gate(
    chunks: list,
    expected_domain: str,
    expected_state: str | None,
    min_chunks: int = 2,
    min_confidence: float = 0.25,
) -> tuple[bool, AbstentionReason | None, ConfidenceBand | None]:
    """Unified evidence gate for EvidenceChunk lists.
    
    Returns (abstained, reason, band).
    Used by both StaticRAGService and WebRAGService.
    """
    from app.contracts import EvidenceChunk
    
    if not chunks:
        return True, AbstentionReason.INSUFFICIENT_EVIDENCE, None

    # Filter to matching domain
    domain_chunks = [c for c in chunks if c.domain == expected_domain]
    if not domain_chunks:
        return True, AbstentionReason.DOMAIN_MISMATCH, None

    # Filter to matching state (central chunks match all states)
    if expected_state:
        state_chunks = [c for c in domain_chunks
                       if c.jurisdiction == "central" or c.state == expected_state]
    else:
        state_chunks = domain_chunks

    if len(state_chunks) < min_chunks:
        return True, AbstentionReason.INSUFFICIENT_EVIDENCE, None

    # Check confidence from scores
    scores = [c.dense_score for c in state_chunks if c.dense_score > 0]
    if not scores:
        return True, AbstentionReason.INSUFFICIENT_EVIDENCE, None

    avg_score = sum(scores) / len(scores)
    top_score = max(scores)

    if top_score < min_confidence:
        return True, AbstentionReason.LOW_CONFIDENCE, None

    # Determine band
    if top_score >= 0.7:
        band = ConfidenceBand.HIGH
    elif top_score >= 0.5:
        band = ConfidenceBand.MEDIUM
    else:
        band = ConfidenceBand.LOW

    return False, None, band
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_evidence_gate_unified.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run existing evidence gate tests to verify no regression**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/ -k "evidence_gate" -v`
Expected: PASS (existing tests still work with `evidence_gate_v2`)

- [ ] **Step 6: Commit**

```bash
git add backend/app/evidence_gate.py backend/tests/test_evidence_gate_unified.py
git commit -m "feat: add unified evidence_gate accepting EvidenceChunk lists"
```

---

## Task 3: Create StaticRAGService

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/static_rag.py`
- Test: `backend/tests/test_services_static_rag.py`

**Interfaces:**
- Consumes: `EvidenceChunk`, `RAGResult`, `evidence_gate` from Tasks 1-2, `retrieve_hybrid` from existing hybrid_retrieval.py
- Produces: `StaticRAGService.retrieve()` returning `RAGResult`

- [ ] **Step 1: Create services package**

```python
# backend/app/services/__init__.py
"""Service layer for RAG pipelines."""
```

- [ ] **Step 2: Write failing test for StaticRAGService**

```python
# backend/tests/test_services_static_rag.py
"""Tests for StaticRAGService."""
from unittest.mock import MagicMock, patch
from app.services.static_rag import StaticRAGService
from app.contracts import RAGResult, EvidenceChunk


def test_static_rag_service_returns_rag_result():
    service = StaticRAGService()
    assert service is not None


@patch("app.services.static_rag.retrieve_hybrid")
@patch("app.services.static_rag.get_supabase")
def test_static_rag_service_retrieve(mock_supabase, mock_retrieve):
    # Mock retrieval to return RetrievedChunk-like objects
    mock_chunk = MagicMock()
    mock_chunk.chunk_id = "pmfby_00012"
    mock_chunk.content = "PMFBY premium rates..."
    mock_chunk.title = "PMFBY Guidelines"
    mock_chunk.source_url = "https://example.com"
    mock_chunk.page = 47
    mock_chunk.section = "Premium Rate"
    mock_chunk.domain = "pmfby"
    mock_chunk.jurisdiction = "central"
    mock_chunk.state = None
    mock_chunk.similarity = 0.85
    mock_retrieve.return_value = [mock_chunk]

    service = StaticRAGService()
    result = service.retrieve(
        embedding=[0.1] * 768,
        query="PMFBY premium rates",
        domain="pmfby",
        state=None,
    )

    assert isinstance(result, RAGResult)
    assert result.abstained is False
    assert len(result.chunks) == 1
    assert result.chunks[0].chunk_id == "pmfby_00012"
    assert result.chunks[0].source_type == "static"


@patch("app.services.static_rag.retrieve_hybrid")
@patch("app.services.static_rag.get_supabase")
def test_static_rag_service_abstains_on_empty(mock_supabase, mock_retrieve):
    mock_retrieve.return_value = []

    service = StaticRAGService()
    result = service.retrieve(
        embedding=[0.1] * 768,
        query="nonexistent topic",
        domain="pmfby",
        state=None,
    )

    assert result.abstained is True
    assert len(result.chunks) == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_services_static_rag.py -v`
Expected: FAIL — `services` package or `StaticRAGService` not found

- [ ] **Step 4: Implement StaticRAGService**

```python
# backend/app/services/static_rag.py
"""Static RAG service — Supabase pgvector hybrid retrieval."""
from __future__ import annotations

import logging
from typing import Any

from app.contracts import EvidenceChunk, RAGResult, AbstentionReason, ConfidenceBand
from app.evidence_gate import evidence_gate
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class StaticRAGService:
    """Encapsulates Supabase pgvector hybrid retrieval + evidence gate."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def retrieve(
        self,
        embedding: list[float],
        query: str,
        domain: str,
        state: str | None,
        k: int | None = None,
    ) -> RAGResult:
        """Run hybrid retrieval → evidence gate → return RAGResult with EvidenceChunks."""
        from app.hybrid_retrieval import retrieve_hybrid
        from app.db import get_supabase

        if k is None:
            k = 25 if self.settings.reranker_enabled else 6

        try:
            chunks = retrieve_hybrid(
                get_supabase(), embedding, query, domain, state, k=k,
            )
        except Exception as e:
            logger.warning("Static RAG retrieval failed: %s", e)
            chunks = []

        # Optional reranker
        if self.settings.reranker_enabled and chunks:
            try:
                from app.providers.reranker import JinaReranker
                reranker = JinaReranker()
                docs_for_rerank = [{"chunk_id": c.chunk_id, "content": c.content} for c in chunks]
                reranked = reranker.rerank(query, docs_for_rerank, top_n=6)
                chunks_by_id = {c.chunk_id: c for c in chunks}
                chunks = [chunks_by_id[r["chunk_id"]] for r in reranked if r["chunk_id"] in chunks_by_id]
            except Exception as e:
                logger.warning("Reranker failed: %s", e)

        # Convert to EvidenceChunks
        evidence_chunks = [
            EvidenceChunk(
                chunk_id=c.chunk_id,
                content=c.content,
                source_type="static",
                title=c.title,
                url=c.source_url,
                page=c.page,
                section=c.section,
                domain=c.domain,
                jurisdiction=c.jurisdiction,
                state=c.state,
                dense_score=c.similarity,
                bm25_score=None,
                rerank_score=None,
                trust_score=None,
                metadata={},
            )
            for c in chunks
        ]

        # Evidence gate
        abstained, reason, band = evidence_gate(
            evidence_chunks, expected_domain=domain, expected_state=state,
        )

        logger.info("Static RAG: %d chunks, abstained=%s, reason=%s",
                     len(evidence_chunks), abstained, reason)

        return RAGResult(
            chunks=evidence_chunks,
            abstained=abstained,
            reason=reason,
            band=band,
            domain=domain,
            metadata={"retrieval_count": len(chunks)},
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_services_static_rag.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/__init__.py backend/app/services/static_rag.py backend/tests/test_services_static_rag.py
git commit -m "feat: add StaticRAGService with EvidenceChunk output"
```

---

## Task 4: Create WebRAGService (eGovAssistant-style 10-step)

**Files:**
- Create: `backend/app/services/web_rag.py`
- Test: `backend/tests/test_services_web_rag.py`

**Interfaces:**
- Consumes: existing `web_rag/service.py` (WebDiscoveryService), `retrieval/bm25_retriever.py`, `retrieval/gemini_reranker.py`, `retrieval/rrf.py`, `security/source_verifier.py`, `evidence_gate` from Task 2
- Produces: `WebRAGService.retrieve()` returning `RAGResult`

- [ ] **Step 1: Write failing test for WebRAGService**

```python
# backend/tests/test_services_web_rag.py
"""Tests for WebRAGService — eGovAssistant-style 10-step pipeline."""
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.web_rag import WebRAGService
from app.contracts import RAGResult


def test_web_rag_service_returns_rag_result():
    service = WebRAGService()
    assert service is not None


@patch("app.services.web_rag.WebDiscoveryService")
@patch("app.services.web_rag.BM25Retriever")
@patch("app.services.web_rag.GeminiReranker")
@patch("app.services.web_rag.SourceVerifier")
def test_web_rag_service_abstains_on_no_discovery(
    mock_verifier, mock_reranker, mock_bm25, mock_discovery
):
    mock_discovery_instance = MagicMock()
    mock_discovery_instance.discover.return_value = {"results": [], "classification": {}}
    mock_discovery.return_value = mock_discovery_instance

    service = WebRAGService()
    classification = MagicMock()
    classification.domain = "pmfby"
    
    result = service.retrieve(query="test query", classification=classification)

    assert isinstance(result, RAGResult)
    assert result.abstained is True


@patch("app.services.web_rag.WebDiscoveryService")
@patch("app.services.web_rag.BM25Retriever")
@patch("app.services.web_rag.GeminiReranker")
@patch("app.services.web_rag.SourceVerifier")
def test_web_rag_service_domain_scope_gate(
    mock_verifier, mock_reranker, mock_bm25, mock_discovery
):
    """Unsupported domains should be blocked before web discovery."""
    service = WebRAGService()
    classification = MagicMock()
    classification.domain = "general"  # unsupported

    result = service.retrieve(query="random question", classification=classification)

    assert result.abstained is True
    # Web discovery should NOT have been called
    mock_discovery.return_value.discover.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_services_web_rag.py -v`
Expected: FAIL — `WebRAGService` not found

- [ ] **Step 3: Implement WebRAGService**

```python
# backend/app/services/web_rag.py
"""Web RAG service — eGovAssistant-style 10-step pipeline.

Adapted from eGovAssistant/Backend/rag/pipeline.py.
Returns evidence only — answer generation is handled by RAGOrchestrator.
"""
from __future__ import annotations

import logging
from typing import Any

from app.contracts import EvidenceChunk, RAGResult, AbstentionReason, ConfidenceBand
from app.evidence_gate import evidence_gate

logger = logging.getLogger(__name__)

# Domains supported by web RAG (matching eGovAssistant's scope gate)
SUPPORTED_WEB_DOMAINS = {
    "pacs_governance", "pacs_computerization", "pmfby",
    "financial_inclusion", "schemes", "agriculture", "grievance",
}


class WebRAGService:
    """eGovAssistant-style 10-step web-grounded RAG pipeline.
    
    Steps:
        1. Domain scope gate
        2. Web discovery (Tavily/Firecrawl)
        3. BM25 ranking
        4. Gemini pre-ranking
        5. RRF fusion
        6. Gemini final reranking
        7. Relevance gate (threshold 60.0)
        8. Source verification
        9. Evidence threshold check
        10. Return EvidenceChunks
    """

    DEFAULT_MIN_RELEVANCE_SCORE = 60.0

    def __init__(
        self,
        bm25_top_k: int = 15,
        gemini_pre_top_k: int = 15,
        final_top_k: int = 8,
        rrf_k: int = 60,
        minimum_relevance_score: float = DEFAULT_MIN_RELEVANCE_SCORE,
        minimum_trust_score: float = 35.0,
    ):
        from app.web_rag.service import WebDiscoveryService
        from app.retrieval.bm25_retriever import BM25Retriever
        from app.retrieval.gemini_reranker import GeminiReranker
        from app.security.source_verifier import SourceVerifier

        self.bm25_top_k = bm25_top_k
        self.gemini_pre_top_k = gemini_pre_top_k
        self.final_top_k = final_top_k
        self.rrf_k = rrf_k
        self.minimum_relevance_score = minimum_relevance_score

        self.web_discovery = WebDiscoveryService()
        self.bm25 = BM25Retriever()
        self.reranker = GeminiReranker()
        self.source_verifier = SourceVerifier(minimum_trust_score=minimum_trust_score)

    def retrieve(
        self,
        query: str,
        classification: Any,
    ) -> RAGResult:
        """Run 10-step web RAG pipeline. Returns RAGResult with EvidenceChunks."""
        # Step 1: Domain scope gate
        domain = getattr(classification, "domain", None) or "general"
        if domain not in SUPPORTED_WEB_DOMAINS:
            logger.info("Web RAG: domain '%s' not supported, abstaining", domain)
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.OUT_OF_SCOPE,
                band=None, domain=domain,
                metadata={"step": "domain_scope_gate"},
            )

        # Step 2: Web discovery
        try:
            discovery = self.web_discovery.discover(query=query, classification=classification)
        except Exception as e:
            logger.error("Web discovery failed: %s", e)
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.PROVIDER_ERROR,
                band=None, domain=domain,
                metadata={"step": "web_discovery", "error": str(e)},
            )

        discovered_results = discovery.get("results", [])
        classification_data = discovery.get("classification", {})

        if not discovered_results:
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                band=None, domain=domain,
                metadata={"step": "web_discovery", "discovery_stage": discovery.get("discovery_stage")},
            )

        # Step 3: BM25 ranking
        try:
            bm25_results = self.bm25.rank_candidates(
                query=query, candidates=discovered_results, top_k=self.bm25_top_k,
            )
        except Exception as e:
            logger.error("BM25 ranking failed: %s", e)
            bm25_results = []

        if not bm25_results:
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                band=None, domain=domain,
                metadata={"step": "bm25_ranking"},
            )

        # Step 4: Gemini pre-ranking
        try:
            gemini_pre_results = self.reranker.pre_rank(
                query=query, candidates=discovered_results,
                top_k=self.gemini_pre_top_k, classification=classification_data,
            )
        except Exception as e:
            logger.error("Gemini pre-ranking failed: %s", e)
            gemini_pre_results = []

        if not gemini_pre_results:
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                band=None, domain=domain,
                metadata={"step": "gemini_pre_ranking"},
            )

        # Step 5: RRF fusion
        from app.retrieval.rrf import reciprocal_rank_fusion
        try:
            fused_results = reciprocal_rank_fusion(
                result_lists=[bm25_results, gemini_pre_results],
                k=self.rrf_k, top_k=None,
            )
        except Exception as e:
            logger.error("RRF fusion failed: %s", e)
            fused_results = []

        if not fused_results:
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                band=None, domain=domain,
                metadata={"step": "rrf_fusion"},
            )

        # Step 6: Gemini final reranking
        try:
            final_results = self.reranker.final_rerank(
                query=query, candidates=fused_results,
                top_k=self.final_top_k, classification=classification_data,
            )
        except Exception as e:
            logger.error("Gemini final reranking failed: %s", e)
            final_results = []

        if not final_results:
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                band=None, domain=domain,
                metadata={"step": "gemini_final_reranking"},
            )

        # Step 7: Relevance gate (eGovAssistant threshold: 60.0)
        relevance_result = self._check_evidence_relevance(final_results)
        if not relevance_result.get("relevant", False):
            logger.info("Web RAG: relevance gate failed (%s)", relevance_result.get("status"))
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.LOW_CONFIDENCE,
                band=None, domain=domain,
                metadata={"step": "relevance_gate", "relevance": relevance_result},
            )

        # Step 8: Source verification
        try:
            verification_result = self.source_verifier.verify_and_filter(final_results)
            accepted_sources = verification_result.get("accepted_sources", [])
        except Exception as e:
            logger.error("Source verification failed: %s", e)
            accepted_sources = final_results  # fallback: use all

        if not accepted_sources:
            return RAGResult(
                chunks=[], abstained=True,
                reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
                band=None, domain=domain,
                metadata={"step": "source_verification"},
            )

        # Step 9: Convert to EvidenceChunks
        evidence_chunks = [
            EvidenceChunk(
                chunk_id=src.get("chunk_id", f"web_{i:03d}"),
                content=src.get("content", src.get("snippet", "")),
                source_type="web",
                title=src.get("title", "Web Source"),
                url=src.get("url", ""),
                page=None,
                section=None,
                domain=classification_data.get("domain", domain),
                jurisdiction=classification_data.get("jurisdiction", "central"),
                state=classification_data.get("state"),
                dense_score=0.0,
                bm25_score=src.get("bm25_score"),
                rerank_score=src.get("rerank_score") or src.get("gemini_score"),
                trust_score=src.get("trust_score"),
                metadata={"source_domain": src.get("source_domain", "")},
            )
            for i, src in enumerate(accepted_sources)
        ]

        # Step 10: Final evidence gate (unified)
        abstained, reason, band = evidence_gate(
            evidence_chunks, expected_domain=domain,
            expected_state=classification_data.get("state"),
        )

        logger.info("Web RAG: %d evidence chunks, abstained=%s", len(evidence_chunks), abstained)

        return RAGResult(
            chunks=evidence_chunks,
            abstained=abstained,
            reason=reason,
            band=band,
            domain=domain,
            metadata={
                "discovery_stage": discovery.get("discovery_stage"),
                "relevance": relevance_result,
                "accepted_count": len(accepted_sources),
            },
        )

    def _check_evidence_relevance(self, results: list[dict]) -> dict:
        """Check if evidence is relevant enough (from eGovAssistant pipeline.py)."""
        if not results:
            return {"relevant": False, "status": "no_final_evidence", "top_score": 0.0, "relevant_count": 0, "scores": []}

        scores = []
        explicitly_inapplicable = []

        for result in results:
            if not isinstance(result, dict):
                continue
            applicable = result.get("rerank_applicable")
            if applicable is False or str(applicable).strip().lower() in {"false", "no", "not_applicable", "irrelevant"}:
                explicitly_inapplicable.append(result)

            raw_score = result.get("rerank_score") or result.get("gemini_score") or result.get("relevance_score")
            try:
                score = float(raw_score if raw_score is not None else 0.0)
            except (TypeError, ValueError):
                score = 0.0
            scores.append(score)

        if not scores:
            return {"relevant": False, "status": "no_relevance_scores", "top_score": 0.0, "relevant_count": 0, "scores": []}

        top_score = max(scores)
        relevant_scores = [s for s in scores if s >= self.minimum_relevance_score]

        if not relevant_scores:
            return {"relevant": False, "status": "below_relevance_threshold", "top_score": top_score, "relevant_count": 0, "scores": scores}

        if len(explicitly_inapplicable) == len(results):
            return {"relevant": False, "status": "all_candidates_inapplicable", "top_score": top_score, "relevant_count": 0, "scores": scores}

        return {"relevant": True, "status": "relevant", "top_score": top_score, "relevant_count": len(relevant_scores), "scores": scores}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_services_web_rag.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/web_rag.py backend/tests/test_services_web_rag.py
git commit -m "feat: add WebRAGService with eGovAssistant-style 10-step pipeline"
```

---

## Task 5: Create RAGOrchestrator

**Files:**
- Create: `backend/app/services/rag_orchestrator.py`
- Test: `backend/tests/test_services_rag_orchestrator.py`

**Interfaces:**
- Consumes: `StaticRAGService` (Task 3), `WebRAGService` (Task 4), `EvidenceChunk`, `RAGResult`, `RAGResponse` (Task 1)
- Produces: `RAGOrchestrator.run()` returning `RAGResponse`

- [ ] **Step 1: Write failing test for RAGOrchestrator**

```python
# backend/tests/test_services_rag_orchestrator.py
"""Tests for RAGOrchestrator — parallel dual-pipeline + merge + generate."""
from unittest.mock import MagicMock, patch
from app.services.rag_orchestrator import RAGOrchestrator
from app.contracts import RAGResult, RAGResponse, EvidenceChunk


def _make_evidence(chunk_id: str, source_type: str = "static", domain: str = "pmfby") -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id, content=f"content for {chunk_id}", source_type=source_type,
        title="Test", url=None, page=1, section="s1", domain=domain,
        jurisdiction="central", state=None, dense_score=0.8, bm25_score=None,
        rerank_score=None, trust_score=None, metadata={},
    )


def test_orchestrator_returns_rag_response():
    orchestrator = RAGOrchestrator()
    assert orchestrator is not None


@patch("app.services.rag_orchestrator.StaticRAGService")
@patch("app.services.rag_orchestrator.WebRAGService")
@patch("app.services.rag_orchestrator.grounded_answer")
def test_orchestrator_merges_evidence(mock_llm, mock_web_cls, mock_static_cls):
    # Mock static RAG
    static_result = RAGResult(
        chunks=[_make_evidence("static_001"), _make_evidence("static_002")],
        abstained=False, reason=None, band=MagicMock(value="high"),
        domain="pmfby", metadata={},
    )
    mock_static = MagicMock()
    mock_static.retrieve.return_value = static_result
    mock_static_cls.return_value = mock_static

    # Mock web RAG
    web_result = RAGResult(
        chunks=[_make_evidence("web_001", source_type="web")],
        abstained=False, reason=None, band=MagicMock(value="medium"),
        domain="pmfby", metadata={},
    )
    mock_web = MagicMock()
    mock_web.retrieve.return_value = web_result
    mock_web_cls.return_value = mock_web

    # Mock LLM
    mock_llm.return_value = "PMFBY premium rates vary by crop [chunk:static_001]."

    orchestrator = RAGOrchestrator()
    result = orchestrator.run(
        query="What are PMFBY premiums?",
        english_query="What are PMFBY premiums?",
        embedding=[0.1] * 768,
        domain="pmfby",
        state=None,
        classification=MagicMock(domain="pmfby"),
        history=None,
    )

    assert isinstance(result, RAGResponse)
    assert result.mode == "dual_rag"
    assert len(result.citations) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_services_rag_orchestrator.py -v`
Expected: FAIL — `RAGOrchestrator` not found

- [ ] **Step 3: Implement RAGOrchestrator**

```python
# backend/app/services/rag_orchestrator.py
"""RAG Orchestrator — parallel dual-pipeline execution + evidence merging + generation."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import Settings, get_settings
from app.contracts import EvidenceChunk, RAGResult, RAGResponse, ConfidenceBand
from app.speech_text import prepare_speech_text, segment_speech

logger = logging.getLogger(__name__)


class RAGOrchestrator:
    """Runs static + web RAG in parallel, merges evidence, generates answer."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def run(
        self,
        query: str,
        english_query: str,
        embedding: list[float],
        domain: str,
        state: str | None,
        classification: Any,
        history: list[dict] | None,
        lang: str = "en",
        session_id: str = "",
    ) -> RAGResponse:
        """Execute dual RAG pipeline → merge → generate → return RAGResponse."""
        from app.services.static_rag import StaticRAGService
        from app.services.web_rag import WebRAGService
        from app.generation import GENERAL_SYSTEM_PROMPT
        from app.llm_fallback import grounded_answer
        from app.providers.groq_llm import GroqLLMProvider
        from app.providers.gemini_llm import GeminiLLMProvider

        static_service = StaticRAGService(self.settings)
        web_service = WebRAGService()

        # Run both pipelines in parallel
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag") as executor:
            static_future = executor.submit(
                static_service.retrieve, embedding, english_query, domain, state,
            )
            web_future = executor.submit(
                web_service.retrieve, query, classification,
            )
            static_result = static_future.result()
            web_result = web_future.result()

        # Determine which sources have evidence
        has_static = not static_result.abstained and len(static_result.chunks) > 0
        has_web = not web_result.abstained and len(web_result.chunks) > 0

        if not has_static and not has_web:
            return self._abstain_response(domain, lang, session_id)

        # Merge evidence
        all_chunks = static_result.chunks + web_result.chunks
        context_str = self._build_context(all_chunks)
        citations = self._build_citations(all_chunks)

        # Build prompt
        prompt = self._build_prompt(english_query, context_str, history, len(static_result.chunks), len(web_result.chunks))

        # System prompt
        system_prompt = (
            "You are a helpful government information assistant. "
            "Synthesize an accurate answer from ALL provided evidence. "
            "Evidence is marked with [chunk:ID] citations — use the EXACT citation "
            "marker shown in the evidence. Treat all evidence as EQUAL inputs. "
            "After EVERY factual sentence, add the citation: [chunk:ID]. "
            "Use ONLY half-width square brackets []. "
            "If evidence is insufficient, say so clearly. "
            "Do NOT mention source types or priorities in your answer — just cite the evidence."
        )

        # Generate answer
        try:
            answer = grounded_answer(
                GroqLLMProvider(self.settings), GeminiLLMProvider(self.settings),
                system_prompt, prompt,
            )
            answer = answer.replace("【", "[").replace("】", "]")
        except Exception as e:
            logger.error("LLM generation failed: %s", e)
            return self._abstain_response(domain, lang, session_id)

        # Handle INSUFFICIENT_EVIDENCE
        if "INSUFFICIENT_EVIDENCE" in answer:
            return self._abstain_response(domain, lang, session_id)

        # Auto-append citations if missing
        has_citation_markers = bool(re.search(r"\[chunk:", answer))
        if not has_citation_markers and static_result.chunks:
            seen = set()
            citation_parts = []
            for c in static_result.chunks[:3]:
                short_id = c.chunk_id[:8]
                if short_id not in seen:
                    seen.add(short_id)
                    citation_parts.append(f"[chunk:{short_id}]")
            if citation_parts:
                answer = answer.rstrip() + " " + " ".join(citation_parts)

        # Determine mode
        if has_static and has_web:
            mode = "dual_rag"
        elif has_static:
            mode = "static"
        else:
            mode = "web"

        # Confidence
        confidence = self._calculate_confidence(static_result, web_result, has_static, has_web)

        return RAGResponse(
            answer=answer,
            language=lang,
            domain=domain,
            confidence=confidence,
            confidence_level=self._confidence_level(confidence),
            citations=citations,
            abstained=False,
            speech_text=prepare_speech_text(answer),
            speech_segments=segment_speech(answer, lang),
            follow_up_question=None,
            mode=mode,
            conversation_id=session_id,
        )

    def _build_context(self, chunks: list[EvidenceChunk]) -> str:
        """Build unified context string from all evidence chunks."""
        parts = []
        for c in chunks:
            if c.source_type == "static":
                parts.append(
                    f"[chunk:{c.chunk_id[:8]}] ({c.title} — §{c.section} — p.{c.page})\n{c.content}"
                )
            else:
                parts.append(
                    f"[chunk:{c.chunk_id}] ({c.title} — web — {c.url})\n{c.content}"
                )
        return "\n\n---\n\n".join(parts) if parts else "No evidence available."

    def _build_citations(self, chunks: list[EvidenceChunk]) -> list[dict]:
        """Build citations list from evidence chunks."""
        citations = []
        for c in chunks:
            citations.append({
                "chunk_id": c.chunk_id[:8] if c.source_type == "static" else c.chunk_id,
                "title": c.title,
                "source": c.source_type,
                "source_label": "Official Document" if c.source_type == "static" else "Web Source",
                "url": c.url or "",
                "page": c.page,
                "section": c.section,
            })
        return citations

    def _build_prompt(
        self, english_query: str, context: str, history: list[dict] | None,
        static_count: int, web_count: int,
    ) -> str:
        """Build merged user prompt for the LLM."""
        hist_text = ""
        if history:
            turns = "\n".join(
                f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content']}"
                for h in history
            )
            hist_text = f"Previous conversation:\n{turns}\n\n"

        source_hint = []
        if static_count > 0:
            source_hint.append(f"{static_count} chunks from official documents")
        if web_count > 0:
            source_hint.append(f"{web_count} chunks from web sources")
        source_str = " and ".join(source_hint) if source_hint else "no evidence sources"

        return (
            f"{hist_text}"
            f"Question: {english_query}\n\n"
            f"{context}\n\n"
            f"Available sources: {source_str}\n"
            f"Synthesize an answer using whichever evidence best answers the question. "
            f"Combine evidence from multiple sources when it strengthens the answer."
        )

    def _calculate_confidence(
        self, static_result: RAGResult, web_result: RAGResult,
        has_static: bool, has_web: bool,
    ) -> float:
        """Calculate combined confidence from both pipelines."""
        band_to_confidence = {"high": 0.9, "medium": 0.7, "low": 0.4}
        static_conf = band_to_confidence.get(
            getattr(static_result.band, "value", ""), 0.4
        ) if static_result.band else 0.4

        if has_static and has_web:
            return min(static_conf + 0.15, 1.0)
        elif has_web:
            return 0.65
        else:
            return static_conf

    def _confidence_level(self, score: float) -> str:
        if score >= 0.7:
            return "high"
        elif score >= 0.5:
            return "moderate"
        elif score > 0.0:
            return "low"
        return "none"

    def _abstain_response(self, domain: str, lang: str, session_id: str) -> RAGResponse:
        """Return an abstained RAGResponse."""
        from app.ui import get_abstain_text
        abstain_msg = get_abstain_text(lang)
        return RAGResponse(
            answer=abstain_msg, language=lang, domain=domain,
            confidence=0.0, confidence_level="none",
            citations=[], abstained=True,
            speech_text=prepare_speech_text(abstain_msg),
            speech_segments=[], follow_up_question=None,
            mode="dual_rag", conversation_id=session_id,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_services_rag_orchestrator.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag_orchestrator.py backend/tests/test_services_rag_orchestrator.py
git commit -m "feat: add RAGOrchestrator for parallel dual-pipeline execution"
```

---

## Task 6: Refactor chat.py to use RAGOrchestrator

**Files:**
- Modify: `backend/app/routes/chat.py`
- Test: `backend/tests/test_chat_route_refactored.py`

**Interfaces:**
- Consumes: `RAGOrchestrator` (Task 5), `RAGResponse` (Task 1)
- Produces: Thin chat route (~200 lines) that delegates to orchestrator

- [ ] **Step 1: Write test for refactored chat route**

```python
# backend/tests/test_chat_route_refactored.py
"""Tests for refactored chat route using RAGOrchestrator."""
from unittest.mock import patch, MagicMock
from app.routes.chat import chat, ChatRequest


@patch("app.routes.chat.RAGOrchestrator")
def test_chat_delegates_to_orchestrator(mock_orch_cls):
    from app.contracts import RAGResponse
    mock_orch = MagicMock()
    mock_orch.run.return_value = RAGResponse(
        answer="PMFBY premiums vary by crop.",
        language="en", domain="pmfby", confidence=0.85,
        confidence_level="high",
        citations=[{"chunk_id": "pmfby_001", "title": "PMFBY Guidelines"}],
        abstained=False, speech_text="PMFBY premiums vary by crop.",
        speech_segments=[], follow_up_question=None,
        mode="dual_rag", conversation_id="session_123",
    )
    mock_orch_cls.return_value = mock_orch

    req = ChatRequest(
        question="What are PMFBY premiums?",
        session_id="session_123",
        language="en",
    )
    result = chat(req)

    assert result["answer"] == "PMFBY premiums vary by crop."
    assert result["abstained"] is False
    assert result["mode"] == "dual_rag"
    mock_orch.run.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_chat_route_refactored.py -v`
Expected: FAIL — chat route still uses old logic

- [ ] **Step 3: Rewrite chat.py to use orchestrator**

Replace the entire content of `backend/app/routes/chat.py` with:

```python
"""Chat route — delegates to RAGOrchestrator for dual-pipeline execution."""
from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.language import detect_query_languages
from app.resolve_response_language import resolve_and_remember
from app.session_store import get_history, get_state, save_message, touch_session, trim_messages
from app.speech_text import prepare_speech_text, segment_speech
from app.ui import get_abstain_text
from app.services.rag_orchestrator import RAGOrchestrator
from app.web_rag.query_classifier import QueryClassifier
from app.grievance.workflow import GrievanceWorkflow

logger = logging.getLogger(__name__)
router = APIRouter()

_query_classifier: QueryClassifier | None = None
_grievance_workflow: GrievanceWorkflow | None = None


def _get_query_classifier() -> QueryClassifier:
    global _query_classifier
    if _query_classifier is None:
        _query_classifier = QueryClassifier()
    return _query_classifier


def _get_grievance_workflow() -> GrievanceWorkflow:
    global _grievance_workflow
    if _grievance_workflow is None:
        _grievance_workflow = GrievanceWorkflow()
    return _grievance_workflow


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str
    language: Literal["en", "hi", "gu", "mr", "bn", "ta"]
    ui_language_explicit: bool = False
    state: str | None = None
    as_of_date: str | None = None
    history: list[dict] | None = None


def _translate_to_english(question: str, input_lang: str, settings) -> str:
    if input_lang == "en":
        return question
    from app.providers.sarvam_translator import SarvamTranslator
    from app.providers.translator import AzureTranslator
    sarvam = SarvamTranslator(settings)
    if sarvam.configured:
        try:
            return sarvam.translate(question, to="en", source=input_lang)
        except Exception:
            logger.warning("Sarvam translation failed, trying Azure")
    try:
        return AzureTranslator(settings).translate(question, to="en", source=input_lang)
    except Exception:
        logger.warning("Azure translation failed, using original")
        return question


def _translate_from_english(text: str, target_lang: str, settings) -> str:
    if target_lang == "en":
        return text
    from app.providers.sarvam_translator import SarvamTranslator
    from app.providers.translator import AzureTranslator
    sarvam = SarvamTranslator(settings)
    if sarvam.configured:
        try:
            return sarvam.translate(text, to=target_lang, source="en")
        except Exception:
            logger.warning("Sarvam back-translation failed")
    try:
        return AzureTranslator(settings).translate(text, to=target_lang, source="en")
    except Exception:
        return text


_DOMAIN_MAP = {"pacs": "pacs_governance", "finlit": "financial_inclusion", "cooperative": "pacs_governance"}


@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    settings = get_settings()
    question = req.question.strip()
    if not question:
        return {"answer": get_abstain_text(req.language), "abstained": True, "language": req.language,
                "domain": "out_of_scope", "confidence": 0.0, "confidence_level": "none",
                "citations": [], "speech_text": "", "speech_segments": [],
                "follow_up_question": None, "mode": "dual_rag", "conversation_id": req.session_id,
                "intent": "general", "entities": []}

    ui_code = req.language if req.ui_language_explicit else None
    lang = resolve_and_remember(req.session_id, req.question, ui_code)
    detected = detect_query_languages(req.question)
    input_lang = detected.get("dominant") or "en"

    english_query = _translate_to_english(req.question, input_lang, settings)

    try:
        history = req.history if req.history is not None else get_history(req.session_id, limit=8)
        from app.providers.embeddings import get_embedding_provider
        from app.domains import get_anchor_store

        provider = get_embedding_provider()
        embedding = provider.embed_texts([english_query], task="retrieval.query")[0]
        domain, _score = get_anchor_store().classify(english_query, embedding)

        classifier = _get_query_classifier()
        classification = classifier.classify(req.question)

        # Grievance → dedicated workflow
        if classification.domain == "grievance":
            workflow = _get_grievance_workflow()
            result = workflow.process_message(
                user_message=req.question, conversation_id=req.session_id, user_id=req.session_id,
            )
            response_text = result.response
            save_message(req.session_id, "user", req.question)
            save_message(req.session_id, "assistant", response_text)
            trim_messages(req.session_id, keep=50)
            return {
                "answer": response_text, "language": lang, "domain": "grievance",
                "intent": classification.intent, "entities": [],
                "confidence": classification.confidence,
                "confidence_level": "high" if classification.confidence >= 0.7 else "moderate" if classification.confidence >= 0.5 else "low",
                "citations": [], "abstained": False,
                "speech_text": prepare_speech_text(response_text),
                "speech_segments": segment_speech(response_text, lang),
                "follow_up_question": None, "mode": "grievance", "conversation_id": req.session_id,
            }

        # Context disambiguation
        rules = getattr(get_anchor_store(), "rules", {})
        has_explicit_keyword = False
        if isinstance(rules, dict):
            has_explicit_keyword = any(
                any(kw in english_query.lower() for kw in kws)
                for kws in rules.values() if isinstance(kws, (list, set, tuple))
            )

        if (not has_explicit_keyword or domain == "out_of_scope") and history:
            user_turns = [h["content"] for h in history if isinstance(h, dict) and h.get("role") == "user" and h.get("content")]
            if user_turns:
                anchor_q = None
                if isinstance(rules, dict):
                    for prev_q in reversed(user_turns):
                        has_kw = any(
                            any(kw in prev_q.lower() for kw in kws)
                            for kws in rules.values() if isinstance(kws, (list, set, tuple))
                        )
                        if has_kw:
                            anchor_q = prev_q
                            break
                if not anchor_q:
                    anchor_q = user_turns[-1]
                contextual_query = f"{anchor_q} {english_query}"
                ctx_embedding = provider.embed_texts([contextual_query], task="retrieval.query")[0]
                ctx_domain, _ = get_anchor_store().classify(contextual_query, ctx_embedding)
                if ctx_domain != "out_of_scope":
                    domain = ctx_domain
                    english_query = contextual_query
                    embedding = ctx_embedding

        resolved_state = req.state if req.state is not None else get_state(req.session_id)
        touch_session(req.session_id, resolved_state, lang)

        # Out-of-scope → abstain
        if domain == "out_of_scope":
            abstain_msg = "I am a cooperative governance assistant and can only answer questions related to cooperatives, agriculture schemes, financial inclusion, and legal provisions in India. Please ask a question within my scope."
            save_message(req.session_id, "user", req.question)
            save_message(req.session_id, "assistant", abstain_msg)
            trim_messages(req.session_id, keep=50)
            return {
                "answer": abstain_msg, "language": lang, "domain": "out_of_scope",
                "intent": "general", "entities": [],
                "confidence": 0.0, "confidence_level": "none",
                "citations": [], "abstained": True,
                "speech_text": prepare_speech_text(abstain_msg),
                "speech_segments": segment_speech(abstain_msg, lang),
                "follow_up_question": None, "mode": "dual_rag", "conversation_id": req.session_id,
            }

        # Delegate to orchestrator
        orchestrator = RAGOrchestrator(settings)
        rag_response = orchestrator.run(
            query=req.question, english_query=english_query, embedding=embedding,
            domain=domain, state=resolved_state, classification=classification,
            history=history, lang=lang, session_id=req.session_id,
        )

        # Translate answer back if needed
        if lang != "en" and not rag_response.abstained:
            rag_response.answer = _translate_from_english(rag_response.answer, lang, settings)
            rag_response.speech_text = prepare_speech_text(rag_response.answer)
            rag_response.speech_segments = segment_speech(rag_response.answer, lang)

        # Save session
        save_message(req.session_id, "user", req.question)
        save_message(req.session_id, "assistant", rag_response.answer)
        trim_messages(req.session_id, keep=50)

        return {
            "answer": rag_response.answer,
            "language": rag_response.language,
            "domain": rag_response.domain,
            "intent": rag_response.domain,
            "entities": [],
            "confidence": rag_response.confidence,
            "confidence_level": rag_response.confidence_level,
            "citations": rag_response.citations,
            "abstained": rag_response.abstained,
            "speech_text": rag_response.speech_text,
            "speech_segments": rag_response.speech_segments,
            "follow_up_question": rag_response.follow_up_question,
            "mode": rag_response.mode,
            "conversation_id": rag_response.conversation_id,
        }

    except Exception as e:
        logger.error("Chat failed: %s", e, exc_info=True)
        abstain_msg = get_abstain_text(lang if 'lang' in locals() else "en")
        return {
            "answer": abstain_msg, "language": lang if 'lang' in locals() else "en",
            "domain": "unknown", "intent": "general", "entities": [],
            "confidence": 0.0, "confidence_level": "none",
            "citations": [], "abstained": True,
            "speech_text": prepare_speech_text(abstain_msg),
            "speech_segments": [], "follow_up_question": None,
            "mode": "dual_rag", "conversation_id": req.session_id,
        }


# ── SSE streaming endpoint ──────────────────────────────────────────────────

_THINKING_MESSAGES = {
    "en": ["Searching official documents & web...", "Analyzing evidence from both sources...", "Preparing answer..."],
    "hi": ["आधिकारिक दस्तावेज़ और वेब खोज रहे हैं...", "दोनों स्रोतों से साक्ष्य का विश्लेषण...", "उत्तर तैयार कर रहे हैं..."],
}


def _sse_event(event: str, data: dict | str) -> str:
    payload = json.dumps(data) if isinstance(data, dict) else data
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Streaming version — same orchestrator, yields SSE events."""
    def generate():
        settings = get_settings()
        ui_code = req.language if req.ui_language_explicit else None
        lang = resolve_and_remember(req.session_id, req.question, ui_code)
        detected = detect_query_languages(req.question)
        input_lang = detected.get("dominant") or "en"
        english_query = _translate_to_english(req.question, input_lang, settings)
        thinking_msgs = _THINKING_MESSAGES.get(lang, _THINKING_MESSAGES["en"])

        try:
            history = req.history if req.history is not None else get_history(req.session_id, limit=8)
            from app.providers.embeddings import get_embedding_provider
            from app.domains import get_anchor_store

            provider = get_embedding_provider()
            embedding = provider.embed_texts([english_query], task="retrieval.query")[0]
            classifier = _get_query_classifier()
            classification = classifier.classify(req.question)

            # Grievance
            if classification.domain == "grievance":
                yield _sse_event("thinking", {"text": thinking_msgs[0]})
                workflow = _get_grievance_workflow()
                result = workflow.process_message(user_message=req.question, conversation_id=req.session_id, user_id=req.session_id)
                answer_text = result.response
                save_message(req.session_id, "user", req.question)
                save_message(req.session_id, "assistant", answer_text)
                trim_messages(req.session_id, keep=50)
                yield _sse_event("metadata", {"domain": "grievance", "confidence": classification.confidence, "confidence_level": "high", "citations": [], "abstained": False, "language": lang})
                for token in answer_text.split(" "):
                    yield _sse_event("token", {"text": token + " "})
                yield _sse_event("done", {})
                return

            # Context disambiguation (same as non-streaming)
            domain, _ = get_anchor_store().classify(english_query, embedding)
            rules = getattr(get_anchor_store(), "rules", {})
            has_explicit_keyword = isinstance(rules, dict) and any(
                any(kw in english_query.lower() for kw in kws)
                for kws in rules.values() if isinstance(kws, (list, set, tuple))
            )
            if (not has_explicit_keyword or domain == "out_of_scope") and history:
                user_turns = [h["content"] for h in history if isinstance(h, dict) and h.get("role") == "user" and h.get("content")]
                if user_turns:
                    anchor_q = None
                    if isinstance(rules, dict):
                        for prev_q in reversed(user_turns):
                            if any(any(kw in prev_q.lower() for kw in kws) for kws in rules.values() if isinstance(kws, (list, set, tuple))):
                                anchor_q = prev_q
                                break
                    if not anchor_q:
                        anchor_q = user_turns[-1]
                    contextual_query = f"{anchor_q} {english_query}"
                    ctx_embedding = provider.embed_texts([contextual_query], task="retrieval.query")[0]
                    ctx_domain, _ = get_anchor_store().classify(contextual_query, ctx_embedding)
                    if ctx_domain != "out_of_scope":
                        domain = ctx_domain
                        english_query = contextual_query
                        embedding = ctx_embedding

            resolved_state = req.state if req.state is not None else get_state(req.session_id)
            touch_session(req.session_id, resolved_state, lang)

            if domain == "out_of_scope":
                yield _sse_event("thinking", {"text": thinking_msgs[1]})
                abstain_msg = "I am a cooperative governance assistant and can only answer questions related to cooperatives, agriculture schemes, financial inclusion, and legal provisions in India. Please ask a question within my scope."
                save_message(req.session_id, "user", req.question)
                save_message(req.session_id, "assistant", abstain_msg)
                trim_messages(req.session_id, keep=50)
                yield _sse_event("metadata", {"domain": "out_of_scope", "confidence": 0.0, "confidence_level": "none", "citations": [], "abstained": True, "language": lang})
                for token in abstain_msg.split(" "):
                    yield _sse_event("token", {"text": token + " "})
                yield _sse_event("done", {})
                return

            # Run orchestrator
            yield _sse_event("thinking", {"text": thinking_msgs[0]})
            orchestrator = RAGOrchestrator(settings)
            rag_response = orchestrator.run(
                query=req.question, english_query=english_query, embedding=embedding,
                domain=domain, state=resolved_state, classification=classification,
                history=history, lang=lang, session_id=req.session_id,
            )

            yield _sse_event("thinking", {"text": thinking_msgs[2]})

            if rag_response.abstained:
                yield _sse_event("metadata", {"domain": domain, "confidence": 0.0, "confidence_level": "none", "citations": [], "abstained": True, "language": lang})
                for token in rag_response.answer.split(" "):
                    yield _sse_event("token", {"text": token + " "})
                yield _sse_event("done", {})
                return

            # Translate back
            answer = rag_response.answer
            if lang != "en":
                answer = _translate_from_english(answer, lang, settings)

            save_message(req.session_id, "user", req.question)
            save_message(req.session_id, "assistant", answer)
            trim_messages(req.session_id, keep=50)

            yield _sse_event("metadata", {
                "domain": rag_response.domain, "confidence": rag_response.confidence,
                "confidence_level": rag_response.confidence_level,
                "citations": rag_response.citations, "abstained": False, "language": lang,
                "mode": rag_response.mode,
            })
            yield _sse_event("done", {})

        except Exception as e:
            logger.error("Stream failed: %s", e, exc_info=True)
            answer = get_abstain_text(lang if 'lang' in locals() else "en")
            yield _sse_event("metadata", {"domain": "unknown", "confidence": 0.0, "confidence_level": "none", "citations": [], "abstained": True, "language": lang})
            for token in answer.split(" "):
                yield _sse_event("token", {"text": token + " "})
            yield _sse_event("done", {})

    return StreamingResponse(generate(), media_type="text/event-stream")
```

Note: Add `from fastapi.responses import StreamingResponse` at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/test_chat_route_refactored.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regression**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (some old tests may need updating to match new imports)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/chat.py backend/tests/test_chat_route_refactored.py
git commit -m "refactor: thin chat route delegating to RAGOrchestrator"
```

---

## Task 7: Clean up old files

**Files:**
- Delete: `backend/app/rag/pipeline.py` (replaced by WebRAGService + RAGOrchestrator)
- Delete: `backend/app/hybrid_retrieval.py` (absorbed into StaticRAGService)
- Delete: `backend/app/retrieval_strategies.py` (absorbed into StaticRAGService)
- Delete: `backend/app/generation.py` (absorbed into RAGOrchestrator + AnswerGenerator)

**Note:** Before deleting, verify no other files import from these modules.

- [ ] **Step 1: Check for remaining imports**

Run: `cd D:\Downloads\New folder\backend && grep -r "from app.rag.pipeline" app/ && grep -r "from app.hybrid_retrieval" app/ && grep -r "from app.retrieval_strategies" app/ && grep -r "from app.generation" app/`
Expected: Only references in the files being deleted or already updated

- [ ] **Step 2: Update any remaining imports**

If any files still import from the old modules, update them to use the new service classes.

- [ ] **Step 3: Delete old files**

```bash
cd D:\Downloads\New folder
rm backend/app/rag/pipeline.py
rm backend/app/hybrid_retrieval.py
rm backend/app/retrieval_strategies.py
rm backend/app/generation.py
```

- [ ] **Step 4: Run full test suite**

Run: `cd D:\Downloads\New folder\backend && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add -A backend/app/
git commit -m "chore: remove old RAG files replaced by service layer"
```

---

## Task 8: Run evaluation and verify no quality regression

**Files:**
- No file changes — verification only

- [ ] **Step 1: Run retrieval eval**

Run: `cd D:\Downloads\New folder && python backend/eval/run_retrieval_eval.py`
Expected: Recall@5 >= 0.975 (current baseline)

- [ ] **Step 2: Run smoke test**

Run: `cd D:\Downloads\New folder && python scripts/smoke_test.py` (or equivalent)
Expected: All smoke tests pass

- [ ] **Step 3: Manual test with sample queries**

Test these queries manually against the running server:
1. "What is PMFBY?" → should return grounded answer with citations
2. "Tell me about PACS governance" → should return grounded answer
3. "What is the weather today?" → should abstain (out of scope)
4. Hindi query: "पीएमएफबीवाई क्या है?" → should return Hindi answer with citations

- [ ] **Step 4: Update PROJECT_STATUS.md**

Update the component status table to reflect:
- `StaticRAGService`: working
- `WebRAGService`: working
- `RAGOrchestrator`: working
- `Chat route`: refactored (thin)
- Remove old component entries

- [ ] **Step 5: Final commit**

```bash
git add PROJECT_STATUS.md
git commit -m "docs: update PROJECT_STATUS after RAG architecture redesign"
```
