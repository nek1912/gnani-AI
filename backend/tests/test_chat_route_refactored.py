"""Tests for refactored chat route (Task 6).

Tests the HTTP layer that delegates to RAGOrchestrator.
Mocks external dependencies (Supabase, LLM, embeddings, translation).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.contracts import (
    ConfidenceBand,
    RAGResponse,
)


client = TestClient(app, raise_server_exceptions=False)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_embedding() -> list[float]:
    return [0.1] * 768


def _make_rag_response(
    answer: str = "PMFBY is a crop insurance scheme.",
    domain: str = "pmfby",
    confidence: float = 0.85,
    abstained: bool = False,
    citations: list[dict] | None = None,
    mode: str = "dual_rag",
) -> RAGResponse:
    return RAGResponse(
        answer=answer,
        language="en",
        domain=domain,
        confidence=confidence,
        confidence_level=ConfidenceBand.HIGH if confidence >= 0.7 else ConfidenceBand.MEDIUM,
        citations=citations if citations is not None else [{"chunk_id": "abcd1234", "title": "PMFBY Guidelines", "source": "static", "source_label": "Official Document"}],
        abstained=abstained,
        speech_text=answer,
        speech_segments=[],
        follow_up_question=None,
        mode=mode,
        conversation_id="test-session",
    )


def _make_classification(domain: str = "pmfby", confidence: float = 0.9) -> MagicMock:
    cls = MagicMock()
    cls.domain = domain
    cls.intent = "INFORMATIONAL"
    cls.confidence = confidence
    cls.jurisdiction = "central"
    cls.state = None
    return cls


# ── Tests: /chat endpoint ───────────────────────────────────────────────────


class TestChatEndpoint:
    """Tests for POST /chat."""

    @patch("app.routes.chat._get_rag_orchestrator")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.touch_session")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_normal_query_returns_rag_response(
        self, mock_detect, mock_resolve, mock_touch, mock_trim,
        mock_save, mock_history, mock_embed_provider, mock_anchor,
        mock_classifier, mock_orchestrator,
    ):
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("pmfby", 0.9)
        mock_anchor.return_value.rules = {}
        mock_classifier.return_value.classify.return_value = _make_classification()
        mock_orchestrator.return_value.run = AsyncMock(return_value=_make_rag_response())

        resp = client.post("/chat", json={
            "question": "What is PMFBY?",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "PMFBY is a crop insurance scheme."
        assert data["domain"] == "pmfby"
        assert data["abstained"] is False
        assert data["confidence"] == 0.85
        assert len(data["citations"]) > 0

    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_empty_question_returns_abstain(
        self, mock_detect, mock_resolve, mock_history,
        mock_embed_provider, mock_anchor, mock_classifier,
    ):
        resp = client.post("/chat", json={
            "question": "   ",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["abstained"] is True
        assert data["domain"] == "unknown"

    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    @patch("app.routes.chat._has_active_grievance")
    def test_grievance_query_delegates_to_workflow(
        self, mock_has_active, mock_detect, mock_resolve, mock_trim, mock_save,
        mock_history, mock_embed_provider, mock_anchor,
        mock_classifier, mock_workflow, mock_ensure_conversation,
    ):
        mock_has_active.return_value = False
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("general", 0.3)
        mock_anchor.return_value.rules = {}
        cls = _make_classification(domain="grievance", confidence=0.95)
        mock_classifier.return_value.classify.return_value = cls
        workflow_result = MagicMock()
        workflow_result.response = "I'll help you file a grievance."
        mock_workflow.return_value.process_message.return_value = workflow_result

        resp = client.post("/chat", json={
            "question": "I want to complain about corruption",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "grievance"
        assert data["answer"] == "I'll help you file a grievance."
        assert data["abstained"] is False
        mock_workflow.return_value.process_message.assert_called_once()

    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_out_of_scope_returns_abstain(
        self, mock_detect, mock_resolve, mock_trim, mock_save,
        mock_history, mock_embed_provider, mock_anchor, mock_classifier,
    ):
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("out_of_scope", 0.1)
        mock_anchor.return_value.rules = {}
        mock_classifier.return_value.classify.return_value = _make_classification(domain="general")

        resp = client.post("/chat", json={
            "question": "What is the weather today?",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["abstained"] is True
        assert data["domain"] == "out_of_scope"

    @patch("app.routes.chat._get_rag_orchestrator")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.touch_session")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_orchestrator_abstain_returns_abstained(
        self, mock_detect, mock_resolve, mock_touch, mock_trim,
        mock_save, mock_history, mock_embed_provider, mock_anchor,
        mock_classifier, mock_orchestrator,
    ):
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("pmfby", 0.9)
        mock_anchor.return_value.rules = {}
        mock_classifier.return_value.classify.return_value = _make_classification()
        mock_orchestrator.return_value.run = AsyncMock(return_value=_make_rag_response(
            answer="No answer found.", abstained=True, confidence=0.0, citations=[],
        ))

        resp = client.post("/chat", json={
            "question": "What is XYZ?",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["abstained"] is True
        assert data["confidence"] == 0.0

    @patch("app.routes.chat._get_rag_orchestrator")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.touch_session")
    @patch("app.routes.chat._translate_from_english")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_hindi_query_translates_answer(
        self, mock_detect, mock_resolve, mock_translate_back, mock_touch,
        mock_trim, mock_save, mock_history, mock_embed_provider,
        mock_anchor, mock_classifier, mock_orchestrator,
    ):
        mock_detect.return_value = {"dominant": "hi"}
        mock_resolve.return_value = "hi"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("pmfby", 0.9)
        mock_anchor.return_value.rules = {}
        mock_classifier.return_value.classify.return_value = _make_classification()
        mock_orchestrator.return_value.run = AsyncMock(return_value=_make_rag_response())
        mock_translate_back.return_value = "PMFBY एक फसल बीमा योजना है।"

        resp = client.post("/chat", json={
            "question": "PMFBY क्या है?",
            "session_id": "test-session",
            "language": "hi",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["language"] == "hi"
        mock_translate_back.assert_called_once()

    @patch("app.routes.chat._get_rag_orchestrator")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.touch_session")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_orchestrator_exception_returns_abstain(
        self, mock_detect, mock_resolve, mock_touch, mock_trim,
        mock_save, mock_history, mock_embed_provider, mock_anchor,
        mock_classifier, mock_orchestrator,
    ):
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("pmfby", 0.9)
        mock_anchor.return_value.rules = {}
        mock_classifier.return_value.classify.return_value = _make_classification()
        mock_orchestrator.return_value.run = AsyncMock(side_effect=RuntimeError("LLM failed"))

        resp = client.post("/chat", json={
            "question": "What is PMFBY?",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["abstained"] is True


# ── Tests: /chat/stream endpoint ────────────────────────────────────────────


class TestChatStreamEndpoint:
    """Tests for POST /chat/stream."""

    @patch("app.routes.chat._get_rag_orchestrator")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.touch_session")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_stream_returns_sse_events(
        self, mock_detect, mock_resolve, mock_touch, mock_trim,
        mock_save, mock_history, mock_embed_provider, mock_anchor,
        mock_classifier, mock_orchestrator,
    ):
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("pmfby", 0.9)
        mock_anchor.return_value.rules = {}
        mock_classifier.return_value.classify.return_value = _make_classification()
        mock_orchestrator.return_value.run = AsyncMock(return_value=_make_rag_response())

        resp = client.post("/chat/stream", json={
            "question": "What is PMFBY?",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        text = resp.text
        assert "event: token" in text
        assert "event: metadata" in text
        assert "event: done" in text
        assert "PMFBY" in text



    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_stream_out_of_scope(
        self, mock_detect, mock_resolve, mock_trim, mock_save,
        mock_history, mock_embed_provider, mock_anchor, mock_classifier,
    ):
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("out_of_scope", 0.1)
        mock_anchor.return_value.rules = {}
        mock_classifier.return_value.classify.return_value = _make_classification(domain="general")

        resp = client.post("/chat/stream", json={
            "question": "Tell me a joke",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        text = resp.text
        assert "out_of_scope" in text
        assert '"abstained": true' in text

    @patch("app.routes.chat.ensure_conversation")
    @patch("app.routes.chat._get_grievance_workflow")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    @patch("app.routes.chat._has_active_grievance")
    def test_stream_grievance(
        self, mock_has_active, mock_detect, mock_resolve, mock_trim, mock_save,
        mock_history, mock_embed_provider, mock_anchor,
        mock_classifier, mock_workflow, mock_ensure_conversation,
    ):
        mock_has_active.return_value = False
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = []
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]
        mock_anchor.return_value.classify.return_value = ("general", 0.3)
        mock_anchor.return_value.rules = {}
        cls = _make_classification(domain="grievance", confidence=0.95)
        mock_classifier.return_value.classify.return_value = cls
        workflow_result = MagicMock()
        workflow_result.response = "Let me help with your grievance."
        mock_workflow.return_value.process_message.return_value = workflow_result

        resp = client.post("/chat/stream", json={
            "question": "I want to complain",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        text = resp.text
        assert "grievance" in text
        assert "Let" in text and "help" in text


# ── Tests: context disambiguation ───────────────────────────────────────────


class TestContextDisambiguation:
    """Tests for AnchorStore context disambiguation logic."""

    @patch("app.routes.chat._get_rag_orchestrator")
    @patch("app.routes.chat._get_query_classifier")
    @patch("app.routes.chat.get_anchor_store")
    @patch("app.routes.chat.get_embedding_provider")
    @patch("app.routes.chat.get_history")
    @patch("app.routes.chat.save_message")
    @patch("app.routes.chat.trim_messages")
    @patch("app.routes.chat.touch_session")
    @patch("app.routes.chat.resolve_and_remember")
    @patch("app.routes.chat.detect_query_languages")
    def test_context_disambiguation_uses_history(
        self, mock_detect, mock_resolve, mock_touch, mock_trim,
        mock_save, mock_history, mock_embed_provider, mock_anchor,
        mock_classifier, mock_orchestrator,
    ):
        mock_detect.return_value = {"dominant": "en"}
        mock_resolve.return_value = "en"
        mock_history.return_value = [
            {"role": "user", "content": "Tell me about PMFBY scheme"},
            {"role": "assistant", "content": "PMFBY is a crop insurance scheme."},
        ]
        mock_embed_provider.return_value.embed_texts.return_value = [_make_embedding()]

        # Use a single mock object so rules persist across multiple get_anchor_store() calls
        anchor_mock = MagicMock()
        # First classify call returns out_of_scope (triggers disambiguation),
        # second call with contextual query returns the actual domain
        anchor_mock.classify.side_effect = [("out_of_scope", 0.1), ("pmfby", 0.85)]
        anchor_mock.rules = {"pmfby": ["pmfbY", "crop insurance", "fasal bima"]}
        mock_anchor.return_value = anchor_mock

        mock_classifier.return_value.classify.return_value = _make_classification()
        mock_orchestrator.return_value.run = AsyncMock(return_value=_make_rag_response())

        resp = client.post("/chat", json={
            "question": "What is the premium?",
            "session_id": "test-session",
            "language": "en",
        })

        assert resp.status_code == 200
        # Verify the orchestrator was called (flow reached RAG step)
        mock_orchestrator.return_value.run.assert_called_once()
        call_kwargs = mock_orchestrator.return_value.run.call_args.kwargs
        # The contextual query should contain the anchor question
        assert "PMFBY" in call_kwargs["english_query"]


# ── Tests: _rag_response_to_dict ────────────────────────────────────────────


class TestRagResponseToDict:
    """Tests for the response format converter."""

    def test_basic_conversion(self):
        from app.routes.chat import _rag_response_to_dict

        resp = _make_rag_response(confidence=0.85)
        result = _rag_response_to_dict(resp, "en", "sess-123")

        assert result["answer"] == "PMFBY is a crop insurance scheme."
        assert result["language"] == "en"
        assert result["domain"] == "pmfby"
        assert result["confidence"] == 0.85
        assert result["confidence_level"] == "high"
        assert result["abstained"] is False
        assert result["conversation_id"] == "sess-123"

    def test_abstained_conversion(self):
        from app.routes.chat import _rag_response_to_dict

        resp = _make_rag_response(abstained=True, confidence=0.0, citations=[])
        result = _rag_response_to_dict(resp, "hi", "sess-456")

        assert result["abstained"] is True
        assert result["confidence"] == 0.0
        assert result["confidence_level"] == "none"
        assert result["citations"] == []


# ── Tests: confidence level ─────────────────────────────────────────────────


class TestConfidenceLevel:
    def test_high(self):
        from app.routes.chat import _confidence_level
        assert _confidence_level(0.9) == "high"
        assert _confidence_level(0.7) == "high"

    def test_moderate(self):
        from app.routes.chat import _confidence_level
        assert _confidence_level(0.6) == "moderate"
        assert _confidence_level(0.5) == "moderate"

    def test_low(self):
        from app.routes.chat import _confidence_level
        assert _confidence_level(0.3) == "low"
        assert _confidence_level(0.1) == "low"

    def test_none(self):
        from app.routes.chat import _confidence_level
        assert _confidence_level(0.0) == "none"


# ── Tests: active grievance workflow priority (multi-turn routing) ──────────


class TestActiveGrievancePriority:
    """Regression: second-turn 'Yes' must route to existing grievance workflow."""

    @patch("app.routes.chat._process_grievance_message")
    @patch("app.routes.chat._has_active_grievance")
    def test_active_grievance_bypasses_classification(
        self, mock_has_active, mock_process,
    ):
        """When an active grievance exists, the message goes to the workflow
        regardless of what QueryClassifier returns."""
        mock_has_active.return_value = True
        mock_process.return_value = "Thank you. What is the date of the incident?"

        resp = client.post("/chat", json={
            "question": "Yes",
            "session_id": "multi-turn-session",
            "language": "en",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "grievance"
        assert data["mode"] == "grievance"
        mock_process.assert_called_once()

    @patch("app.routes.chat._process_grievance_message")
    @patch("app.routes.chat._has_active_grievance")
    def test_completed_grievance_does_not_trigger_workflow(
        self, mock_has_active, mock_process,
    ):
        """A completed grievance should NOT route to the workflow."""
        mock_has_active.return_value = False
        mock_process.return_value = "should not be called"

        resp = client.post("/chat", json={
            "question": "Yes",
            "session_id": "completed-session",
            "language": "en",
        })

        assert resp.status_code == 200
        mock_process.assert_not_called()

    @patch("app.routes.chat._has_active_grievance")
    def test_stream_active_grievance_bypasses_classification(
        self, mock_has_active,
    ):
        """Streaming route: active grievance state routes to workflow."""
        mock_has_active.return_value = True

        with patch("app.routes.chat._process_grievance_message") as mock_process:
            mock_process.return_value = "What is the date of the incident?"

            resp = client.post("/chat/stream", json={
                "question": "Yes",
                "session_id": "multi-turn-stream",
                "language": "en",
            })

            assert resp.status_code == 200
            text = resp.text
            assert "grievance" in text
            assert "date" in text.lower()
            mock_process.assert_called_once()

    @patch("app.routes.chat._has_active_grievance")
    def test_stream_completed_grievance_does_not_trigger_workflow(
        self, mock_has_active,
    ):
        """Streaming route: completed grievance does NOT route to workflow."""
        mock_has_active.return_value = False

        with patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
            from app.contracts import RAGResponse, ConfidenceBand
            mock_orch.return_value.run = AsyncMock(return_value=RAGResponse(
                answer="PMFBY is a scheme.",
                language="en", domain="pmfby", confidence=0.85,
                confidence_level=ConfidenceBand.HIGH,
                citations=[], abstained=False, speech_text="PMFBY is a scheme.",
                speech_segments=[], follow_up_question=None,
                mode="dual_rag", conversation_id="completed-stream",
            ))

            with patch("app.routes.chat._get_query_classifier") as mock_cls, \
                 patch("app.routes.chat.get_anchor_store") as mock_anchor, \
                 patch("app.routes.chat.get_embedding_provider") as mock_emb, \
                 patch("app.routes.chat.get_history") as mock_hist, \
                 patch("app.routes.chat.save_message"), \
                 patch("app.routes.chat.trim_messages"), \
                 patch("app.routes.chat.touch_session"), \
                 patch("app.routes.chat.resolve_and_remember") as mock_resolve, \
                 patch("app.routes.chat.detect_query_languages") as mock_detect:
                mock_detect.return_value = {"dominant": "en"}
                mock_resolve.return_value = "en"
                mock_hist.return_value = []
                mock_emb.return_value.embed_texts.return_value = [[0.1] * 768]
                mock_anchor.return_value.classify.return_value = ("pmfby", 0.9)
                mock_anchor.return_value.rules = {}
                cls = MagicMock()
                cls.domain = "pmfby"
                cls.intent = "INFORMATIONAL"
                cls.confidence = 0.85
                mock_cls.return_value.classify.return_value = cls

                resp = client.post("/chat/stream", json={
                    "question": "Yes",
                    "session_id": "completed-stream",
                    "language": "en",
                })

                assert resp.status_code == 200
                text = resp.text
                assert "pmfby" in text.lower() or "PMFBY" in text

