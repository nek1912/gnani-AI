import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"


def test_chat_request_accepts_history():
    """ChatRequest should accept an optional history field."""
    payload = {
        "question": "What are the eligibility criteria?",
        "session_id": str(uuid.uuid4()),
        "language": "en",
        "state": None,
        "history": [
            {"role": "user", "content": "What is PMFBY?"},
            {"role": "assistant", "content": "PMFBY is a crop insurance scheme."},
        ],
    }
    from app.routes.chat import ChatRequest
    req = ChatRequest(**payload)
    assert len(req.history) == 2
    assert req.history[0]["role"] == "user"


def test_chat_request_history_optional():
    """history=None should be valid."""
    from app.routes.chat import ChatRequest
    req = ChatRequest(
        question="test", session_id=str(uuid.uuid4()),
        language="en", state=None
    )
    assert req.history is None


@patch("app.routes.chat.trim_messages")
@patch("app.routes.chat.save_message")
@patch("app.routes.chat.get_history")
@patch("app.routes.chat._resolve_context")
def test_chat_sends_history_to_prompt(
    mock_resolve, mock_history, mock_save, mock_trim,
):
    """When history is provided, it should be used by the orchestrator."""
    ctx = MagicMock()
    ctx.settings = MagicMock()
    ctx.lang = "en"
    ctx.input_lang = "en"
    ctx.english_query = "What are the criteria?"
    ctx.embedding = [0.5] * 768
    ctx.domain = "pmfby"
    ctx.classification = MagicMock()
    ctx.classification.domain = "pmfby"
    ctx.history = [{"role": "user", "content": "What is PMFBY?"}]
    ctx.resolved_state = None
    mock_resolve.return_value = ctx

    mock_history.return_value = [{"role": "user", "content": "What is PMFBY?"}]

    with patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
        resp = MagicMock()
        resp.answer = "Answer [chunk:aaaabbbb]."
        resp.domain = "pmfby"
        resp.confidence = 0.8
        resp.citations = []
        resp.abstained = False
        resp.speech_text = "Answer."
        resp.speech_segments = [{"text": "Answer.", "language": "en"}]
        resp.follow_up_question = None
        resp.mode = "static"
        mock_orch.return_value.run = AsyncMock(return_value=resp)

        payload = {
            "question": "What are the criteria?",
            "session_id": str(uuid.uuid4()),
            "language": "en",
            "state": None,
            "history": [{"role": "user", "content": "What is PMFBY?"}],
        }

        r = client.post("/chat", json=payload)
        assert r.status_code == 200
        assert mock_save.call_count == 2


@patch("app.routes.chat.trim_messages")
@patch("app.routes.chat.save_message")
@patch("app.routes.chat.get_history")
@patch("app.routes.chat._resolve_context")
def test_chat_persists_on_out_of_scope(
    mock_resolve, mock_history, mock_save, mock_trim,
):
    """Out-of-scope path should also persist messages."""
    ctx = MagicMock()
    ctx.settings = MagicMock()
    ctx.lang = "en"
    ctx.input_lang = "en"
    ctx.english_query = "What is the weather?"
    ctx.embedding = [0.5] * 768
    ctx.domain = "out_of_scope"
    ctx.classification = MagicMock()
    ctx.classification.domain = "out_of_scope"
    ctx.history = None
    ctx.resolved_state = None
    mock_resolve.return_value = ctx

    payload = {
        "question": "What is the weather?",
        "session_id": str(uuid.uuid4()),
        "language": "en",
        "state": None,
    }

    r = client.post("/chat", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "out_of_scope"
    assert mock_save.call_count == 2
    mock_trim.assert_called_once_with(payload["session_id"], keep=50, user_id="test-user")


@patch("app.routes.chat.trim_messages")
@patch("app.routes.chat.save_message")
@patch("app.routes.chat.get_history")
@patch("app.routes.chat._resolve_context")
def test_chat_persists_on_success(
    mock_resolve, mock_history, mock_save, mock_trim,
):
    """Successful RAG path should persist messages."""
    ctx = MagicMock()
    ctx.settings = MagicMock()
    ctx.lang = "en"
    ctx.input_lang = "en"
    ctx.english_query = "What is PMFBY?"
    ctx.embedding = [0.5] * 768
    ctx.domain = "pmfby"
    ctx.classification = MagicMock()
    ctx.classification.domain = "pmfby"
    ctx.history = []
    ctx.resolved_state = None
    mock_resolve.return_value = ctx

    mock_history.return_value = []

    with patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
        resp = MagicMock()
        resp.answer = "Answer [chunk:aaaabbbb]."
        resp.domain = "pmfby"
        resp.confidence = 0.8
        resp.citations = []
        resp.abstained = False
        resp.speech_text = "Answer."
        resp.speech_segments = [{"text": "Answer.", "language": "en"}]
        resp.follow_up_question = None
        resp.mode = "static"
        mock_orch.return_value.run = AsyncMock(return_value=resp)

        payload = {
            "question": "What is PMFBY?",
            "session_id": str(uuid.uuid4()),
            "language": "en",
            "state": None,
        }

        r = client.post("/chat", json=payload)
        assert r.status_code == 200
        assert mock_save.call_count == 2
        mock_trim.assert_called_once_with(payload["session_id"], keep=50, user_id="test-user")


@respx.mock
def test_chat_resolves_contextual_followup_question(respx_mock):
    """When follow-up question alone is out_of_scope, use history to resolve contextual domain."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    RPC_PATH = "/rest/v1/rpc/match_chunks"
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[{
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": "pmfby-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "PMFBY eligibility: eligible farmers are covered.", "similarity": 0.72,
            "source_url": "https://pmfby.gov.in/faq", "source_file": "pmfby.gov.in/faq",
            "domain": "pmfby", "jurisdiction": "central", "state": None}, {
            "chunk_id": "bbbbbbbb-5555-6666-7777-888888888888",
            "stable_chunk_id": "pmfby-guidelines:p4:c0",
            "document_id": "eeee1111-2222-3333-4444-555555555555",
            "title": "PMFBY Guidelines", "page": 4, "page_start": 4, "page_end": 4,
            "section": "Coverage", "subsection": None, "clause": None,
            "content": "PMFBY coverage extends to notified crops.", "similarity": 0.51,
            "source_url": "https://pmfby.gov.in/guidelines",
            "source_file": "pmfby.gov.in/guidelines",
            "domain": "pmfby", "jurisdiction": "central", "state": None}]))
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "PMFBY eligibility: All farmers... [chunk:aaaaaaaa]."}}]}))

    payload = {
        "question": "What are the eligibility criteria?",
        "session_id": str(uuid.uuid4()),
        "language": "en",
        "state": None,
        "history": [{"role": "user", "content": "What is PMFBY?"}],
    }

    r = client.post("/chat", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "pmfby"
    assert "PMFBY eligibility" in body["answer"]
