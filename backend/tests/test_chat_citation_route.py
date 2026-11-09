"""Test citation verification at the route level.

Tests the actual call path through the RAGOrchestrator.
Since the orchestrator now handles citation auto-append and verification
internally, these tests verify the orchestrator integration rather than
the old route-level verifier.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
RPC_PATH = "/rest/v1/rpc/match_chunks"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL_PREFIX = "https://generativelanguage.googleapis.com/v1beta/models/"

PAYLOAD = {"question": "What is PACS?", "session_id": str(uuid.uuid4()),
           "language": "en", "state": None}


@respx.mock
def test_answered_with_valid_citations(respx_mock):
    """Chat route returns a valid response when orchestrator produces citations."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[{
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": "pmfby-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "PACS membership rules.", "similarity": 0.72,
            "source_url": "https://pmfby.gov.in/faq", "source_file": "pmfby.gov.in/faq",
            "domain": "pmfby", "jurisdiction": "central", "state": None}, {
            "chunk_id": "bbbbbbbb-5555-6666-7777-888888888888",
            "stable_chunk_id": "pmfby-guidelines:p4:c0",
            "document_id": "eeee1111-2222-3333-4444-555555555555",
            "title": "PMFBY Guidelines", "page": 4, "page_start": 4, "page_end": 4,
            "section": "Coverage", "subsection": None, "clause": None,
            "content": "Coverage extends to notified crops.", "similarity": 0.51,
            "source_url": "https://pmfby.gov.in/guidelines",
            "source_file": "pmfby.gov.in/guidelines",
            "domain": "pmfby", "jurisdiction": "central", "state": None}]))
    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "PACS requires membership [chunk:aaaaaaaa]."}}]}))
    r = client.post("/chat", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is False
    assert body["confidence"] > 0


@patch("app.routes.chat.trim_messages")
@patch("app.routes.chat.save_message")
@patch("app.routes.chat.get_history")
@patch("app.routes.chat._resolve_context")
def test_route_delegates_citation_handling_to_orchestrator(
    mock_resolve, mock_history, mock_save, mock_trim,
):
    """Citation verification is handled by the orchestrator, not the route."""
    ctx = MagicMock()
    ctx.settings = MagicMock()
    ctx.lang = "en"
    ctx.input_lang = "en"
    ctx.english_query = "What is PACS?"
    ctx.embedding = [0.5] * 768
    ctx.domain = "pacs_governance"
    ctx.classification = MagicMock()
    ctx.classification.domain = "pacs_governance"
    ctx.history = []
    ctx.resolved_state = None
    mock_resolve.return_value = ctx
    mock_history.return_value = []

    with patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
        resp = MagicMock()
        resp.answer = "PACS requires membership [chunk:aaaaaaaa]."
        resp.domain = "pacs_governance"
        resp.confidence = 0.8
        resp.citations = [{"chunk_id": "aaaaaaaa", "title": "PMFBY FAQ"}]
        resp.abstained = False
        resp.speech_text = "PACS requires membership."
        resp.speech_segments = [{"text": "PACS requires membership.", "language": "en"}]
        resp.follow_up_question = None
        resp.mode = "static"
        mock_orch.return_value.run = AsyncMock(return_value=resp)

        payload = {
            "question": "What is PACS?",
            "session_id": str(uuid.uuid4()),
            "language": "en",
            "state": None,
        }
        r = client.post("/chat", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["abstained"] is False
        assert len(body["citations"]) == 1
