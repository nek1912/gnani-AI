"""Tests for unified RAG models: EvidenceChunk, RAGResult, RAGResponse."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import (
    AbstentionReason,
    ConfidenceBand,
    EvidenceChunk,
    RAGResponse,
    RAGResult,
)


# ---------------------------------------------------------------------------
# EvidenceChunk
# ---------------------------------------------------------------------------

class TestEvidenceChunk:
    def test_minimal_static(self) -> None:
        c = EvidenceChunk(chunk_id="c1", content="text", source_type="static")
        assert c.chunk_id == "c1"
        assert c.source_type == "static"
        assert c.title == ""
        assert c.url == ""
        assert c.page is None
        assert c.dense_score is None
        assert c.metadata == {}

    def test_minimal_web(self) -> None:
        c = EvidenceChunk(chunk_id="c2", content="html", source_type="web")
        assert c.source_type == "web"

    def test_all_fields(self) -> None:
        c = EvidenceChunk(
            chunk_id="c3",
            content="full",
            source_type="web",
            title="Title",
            url="https://example.com",
            page=5,
            section="Sec 3",
            domain="cooperative",
            jurisdiction="central",
            state="karnataka",
            dense_score=0.91,
            bm25_score=0.75,
            rerank_score=0.88,
            trust_score=0.95,
            metadata={"custom": True},
        )
        assert c.dense_score == 0.91
        assert c.state == "karnataka"
        assert c.metadata == {"custom": True}

    def test_invalid_source_type(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceChunk(chunk_id="c4", content="x", source_type="bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RAGResult
# ---------------------------------------------------------------------------

class TestRAGResult:
    def test_empty_result(self) -> None:
        r = RAGResult()
        assert r.chunks == []
        assert r.abstained is False
        assert r.reason is None
        assert r.band is None

    def test_with_chunks(self) -> None:
        chunk = EvidenceChunk(chunk_id="c1", content="a", source_type="static")
        r = RAGResult(chunks=[chunk], domain="cooperative")
        assert len(r.chunks) == 1
        assert r.domain == "cooperative"

    def test_abstained(self) -> None:
        r = RAGResult(
            abstained=True,
            reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
            band=ConfidenceBand.LOW,
        )
        assert r.abstained is True
        assert r.reason == AbstentionReason.INSUFFICIENT_EVIDENCE

    def test_invalid_reason(self) -> None:
        with pytest.raises(ValidationError):
            RAGResult(reason="NOPE")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RAGResponse
# ---------------------------------------------------------------------------

class TestRAGResponse:
    def test_minimal(self) -> None:
        resp = RAGResponse(answer="hello")
        assert resp.answer == "hello"
        assert resp.language == "en"
        assert resp.confidence == 0.0
        assert resp.confidence_level == ConfidenceBand.LOW
        assert resp.abstained is False
        assert resp.mode == "rag"

    def test_full_fields(self) -> None:
        resp = RAGResponse(
            answer="Full answer",
            language="hi",
            domain="agriculture",
            confidence=0.85,
            confidence_level=ConfidenceBand.HIGH,
            citations=[{"chunk_id": "c1", "title": "Act"}],
            abstained=False,
            speech_text="speech",
            speech_segments=[{"start": 0, "end": 1}],
            follow_up_question="Need more?",
            mode="web",
            conversation_id="conv-123",
        )
        assert resp.confidence == 0.85
        assert resp.follow_up_question == "Need more?"
        assert resp.conversation_id == "conv-123"

    def test_serialization_roundtrip(self) -> None:
        resp = RAGResponse(answer="test", confidence=0.7)
        data = resp.model_dump()
        resp2 = RAGResponse.model_validate(data)
        assert resp2.answer == "test"
        assert resp2.confidence == 0.7
