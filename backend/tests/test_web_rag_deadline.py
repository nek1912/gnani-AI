"""WebRAG timeout-lifecycle regression tests.

Reproduces the live-demo failure: WebRAG's recovery loop kept running past
the orchestrator's ``web_rag_timeout_s`` budget, computed a strong result
(8 chunks, top relevance 67.2) AFTER the orchestrator had already fallen
back to static-only, and the late result was discarded (orchestrator saw
``web=0 chunks`` while the logs showed success).

Root cause: the orchestrator abandons ``asyncio.to_thread(retrieve)`` via
``wait_for`` + ``task.cancel()``, which does NOT stop the worker thread
(verified empirically). ``WebRAGService.retrieve`` had no notion of the
outer budget, so recovery rounds started with no time left.

Fix contract locked in by these tests:
  - ``WebRAGService.retrieve`` accepts a cooperative monotonic ``deadline``.
  - No NEW recovery round starts once the deadline has passed.
  - The orchestrator passes ``started + web_rag_timeout_s`` as ``deadline``
    on both the web-only and dual paths.
  - Retrieval quality is otherwise unchanged (thresholds, RRF, BM25,
    verifier, branch logic, 2-round bound all untouched).
"""

from __future__ import annotations

import time
from unittest.mock import patch

from app.config import Settings
from app.contracts import AbstentionReason, EvidenceChunk, RAGResult
from app.services.rag_orchestrator import RAGOrchestrator
from app.services.web_rag import WebRAGService
from app.web_rag.query_classifier import QueryClassification


def _settings(**overrides) -> Settings:
    defaults = {
        "groq_api_key": "test-groq-key",
        "gemini_api_key": "test-gemini-key",
        "jina_api_key": "test-jina-key",
        "supabase_url": "https://test.supabase.co",
        "supabase_service_key": "test-key",
        "reranker_enabled": False,
        "sarvam_api_key": "",
        "sarvam_api_key_2": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _classification() -> QueryClassification:
    return QueryClassification(
        domain="pmfby", jurisdiction="state", state="Gujarat",
        intent="INFORMATIONAL", confidence=0.8,
    )


def _source(chunk_id, score=85.0):
    return {
        "chunk_id": chunk_id,
        "source_url": "https://pmfby.gov.in/guidelines", "url": "https://pmfby.gov.in/guidelines",
        "title": "PMFBY guidelines", "web_title": "PMFBY guidelines",
        "text": "PMFBY guidelines text", "content": "PMFBY guidelines text",
        "bm25_score": 1.0, "gemini_score": score, "rerank_score": score,
        "rerank_applicable": True, "official": True,
        "trusted_secondary": False, "source_tier": 4,
        "document_role": "instrument", "mandate_fit": 0.30,
        "query_domain": "pmfby", "jurisdiction": "central", "state": None,
    }


def _discovery(results):
    return {
        "results": results,
        "classification": {"domain": "pmfby", "jurisdiction": "state", "state": "Gujarat"},
        "discovery_metadata": {"branches_run": ["primary"], "facet_coverage": {}},
    }


def _run_retrieve(service, discoveries, **kwargs):
    """retrieve() with mocked discover + passthrough rerank (no network)."""
    if not isinstance(discoveries, list):
        discoveries = [discoveries]
    with patch.object(
        service.web_discovery, "discover", side_effect=list(discoveries)
    ), patch.object(
        service.reranker, "final_rerank",
        side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
    ):
        return service.retrieve(query="Crop insurance Gujarat", **kwargs)


class TestRetrieveDeadline:
    def test_expired_deadline_starts_no_recovery_rounds(self):
        """Core regression: with the budget already exhausted, retrieve()
        must NOT start any recovery round (previously it always ran all 2,
        even when the caller had already timed out)."""
        service = WebRAGService()
        weak = _discovery([_source("w1", score=5.0)])
        with patch.object(
            service.web_discovery, "discover", return_value=weak,
        ) as mock_discover, patch.object(
            service.reranker, "final_rerank",
            side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
        ):
            result = service.retrieve(
                query="Crop insurance Gujarat",
                deadline=time.monotonic() - 1.0,  # budget already gone
            )
        assert mock_discover.call_count == 1  # initial only, zero recovery
        assert result.abstained is True
        assert result.metadata["recovery_rounds"] == 0
        assert result.metadata.get("deadline_stopped_recovery") is True

    def test_no_deadline_preserves_two_round_bound(self):
        """Without a deadline, behavior is exactly the legacy bound:
        initial + 2 recovery rounds."""
        service = WebRAGService()
        weak = _discovery([_source("w1", score=5.0)])
        with patch.object(
            service.web_discovery, "discover", return_value=weak,
        ) as mock_discover, patch.object(
            service.reranker, "final_rerank",
            side_effect=lambda query, candidates, top_k, classification: candidates[:top_k],
        ):
            result = service.retrieve(query="Crop insurance Gujarat")
        assert mock_discover.call_count == 3
        assert result.metadata["recovery_rounds"] == 2
        assert result.metadata.get("deadline_stopped_recovery", False) is False

    def test_future_deadline_allows_recovery_then_pass(self):
        """A live budget must not change retrieval quality: weak first
        attempt followed by a good recovery round still succeeds."""
        service = WebRAGService()
        weak = _discovery([_source("w1", score=5.0)])
        good = _discovery([_source("g1", score=85.0)])
        result = _run_retrieve(
            service, [weak, good],
            deadline=time.monotonic() + 60.0,
        )
        assert result.abstained is False
        assert len(result.chunks) == 1
        assert result.metadata["recovery_rounds"] == 1

    def test_first_attempt_always_runs_even_past_deadline(self):
        """The initial attempt is never skipped: an immediately-good
        result is delivered even with an expired deadline."""
        service = WebRAGService()
        good = _discovery([_source("g1", score=85.0)])
        result = _run_retrieve(
            service, [good],
            deadline=time.monotonic() - 1.0,
        )
        assert result.abstained is False
        assert len(result.chunks) == 1
        assert result.metadata["recovery_rounds"] == 0


def _chunk(cid="web-abc12345") -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=cid, content="Farmer registry: gujrat farmer registry portal.",
        source_type="web", title="Registry portal", url="https://example.gov.in",
        domain="schemes", jurisdiction="state", state="Gujarat", dense_score=67.2,
    )


class TestOrchestratorTimeoutLifecycle:
    async def test_passes_deadline_to_web_retrieve(self):
        """The orchestrator must hand its timeout budget to WebRAG so
        recovery can stop starting rounds the caller will never wait for."""
        orch = RAGOrchestrator(_settings(web_rag_timeout_s=5.0))
        seen: dict = {}
        empty = RAGResult(
            chunks=[], abstained=True,
            reason=AbstentionReason.NO_ELIGIBLE_SOURCE, domain="schemes",
        )

        def fake_retrieve(**kwargs):
            seen.update(kwargs)
            return empty

        with patch.object(orch._web_rag, "retrieve", side_effect=fake_retrieve):
            before = time.monotonic()
            await orch._run_pipelines(
                english_query="farmer registry Gujarat",
                embedding=[0.0] * 8, domain="schemes", state="Gujarat",
                classification=_classification(), mode="web",
            )
        assert "deadline" in seen, "orchestrator did not pass a deadline"
        assert abs(seen["deadline"] - (before + 5.0)) < 2.0

    async def test_slow_web_falls_back_safely(self):
        """A genuinely timed-out WebRAG still falls back to an empty,
        abstained web result within the budget (safe abstention preserved)."""
        orch = RAGOrchestrator(_settings(web_rag_timeout_s=0.2))

        def slow_retrieve(**kwargs):
            time.sleep(2.0)  # far past the 0.2s budget
            return RAGResult(
                chunks=[_chunk()], abstained=False, domain="schemes",
            )

        with patch.object(orch._web_rag, "retrieve", side_effect=slow_retrieve):
            started = time.monotonic()
            _static, web = await orch._run_pipelines(
                english_query="farmer registry Gujarat",
                embedding=[0.0] * 8, domain="schemes", state="Gujarat",
                classification=_classification(), mode="web",
            )
            elapsed = time.monotonic() - started
        assert web.abstained is True
        assert web.chunks == []
        assert web.reason == AbstentionReason.PROVIDER_UNAVAILABLE
        assert elapsed < 2.0, f"fallback took {elapsed:.2f}s, budget not enforced"

    async def test_fast_web_result_reaches_orchestrator(self):
        """A WebRAG result returned BEFORE the timeout must reach the
        orchestrator (delivery path intact)."""
        orch = RAGOrchestrator(_settings(web_rag_timeout_s=5.0))
        good = RAGResult(
            chunks=[_chunk()], abstained=False, domain="schemes",
        )
        with patch.object(orch._web_rag, "retrieve", return_value=good):
            _static, web = await orch._run_pipelines(
                english_query="farmer registry Gujarat",
                embedding=[0.0] * 8, domain="schemes", state="Gujarat",
                classification=_classification(), mode="web",
            )
        assert web.abstained is False
        assert len(web.chunks) == 1

    async def test_web_exception_stays_isolated(self):
        """A provider exception inside WebRAG must not break the pipeline:
        isolated to an empty abstained web result."""
        orch = RAGOrchestrator(_settings(web_rag_timeout_s=5.0))

        def boom(**kwargs):
            raise RuntimeError("tavily 429")

        with patch.object(orch._web_rag, "retrieve", side_effect=boom):
            _static, web = await orch._run_pipelines(
                english_query="farmer registry Gujarat",
                embedding=[0.0] * 8, domain="schemes", state="Gujarat",
                classification=_classification(), mode="web",
            )
        assert web.abstained is True
        assert web.chunks == []
