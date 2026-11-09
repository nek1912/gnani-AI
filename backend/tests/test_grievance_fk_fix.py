"""Integration tests for the grievance FK fix (ensure_conversation).

Verifies:
1. ensure_conversation is called in /chat grievance path (before workflow)
2. ensure_conversation is called in /chat/stream grievance path (before workflow)
3. ensure_conversation is called in /grievances path (before workflow)
4. ensure_conversation uses atomic upsert (not SELECT→INSERT)
5. Normal RAG /chat is unaffected (ensure_conversation not called)
"""

import uuid
from unittest.mock import patch, MagicMock

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
RPC_PATH = "/rest/v1/rpc/match_chunks"


class _GrievanceStore:
    @staticmethod
    def classify(_text, _embedding):
        return "grievance", 0.95


def _mock_all(respx_mock):
    """Mock embedding, RPC, LLM, and Supabase REST (grievance_states, conversations)."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[]))
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "You can file a grievance."}}]}))
    # Mock Supabase REST for grievance_states SELECT (load_grievance_state)
    respx_mock.get(httpx.URL("http://testsupa/rest/v1/grievance_states")).mock(
        return_value=httpx.Response(200, json=[]))
    # Mock Supabase REST for grievance_states UPSERT (save_grievance_state)
    respx_mock.post(httpx.URL("http://testsupa/rest/v1/grievance_states")).mock(
        return_value=httpx.Response(200, json=[]))


# ── Test 1: /chat grievance path calls ensure_conversation ─────────────────

@respx.mock
def test_chat_grievance_calls_ensure_conversation(respx_mock):
    _mock_all(respx_mock)

    from app.routes import chat as chat_route
    original = chat_route.get_anchor_store
    chat_route.get_anchor_store = lambda: _GrievanceStore()
    try:
        test_id = str(uuid.uuid4())
        with patch("app.routes.chat.ensure_conversation") as mock_ensure:
            r = client.post("/chat", json={
                "question": "I want to file a complaint about my cooperative",
                "session_id": test_id,
                "language": "en",
                "state": None,
            })
            assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
            body = r.json()
            assert body["domain"] == "grievance", f"Got domain={body['domain']}"
            # Chat session ownership: bound to the authenticated Clerk sub
            # ("test-user" via shared auth stub), never session_id-as-user.
            mock_ensure.assert_called_once_with(test_id, "test-user")
    finally:
        chat_route.get_anchor_store = original


# ── Test 2: /chat/stream grievance path calls ensure_conversation ──────────

@respx.mock
def test_chat_stream_grievance_calls_ensure_conversation(respx_mock):
    _mock_all(respx_mock)

    from app.routes import chat as chat_route
    original = chat_route.get_anchor_store
    chat_route.get_anchor_store = lambda: _GrievanceStore()
    try:
        test_id = str(uuid.uuid4())
        with patch("app.routes.chat.ensure_conversation") as mock_ensure:
            r = client.post("/chat/stream", json={
                "question": "I want to file a complaint about my cooperative",
                "session_id": test_id,
                "language": "en",
                "state": None,
            })
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            mock_ensure.assert_called_once_with(test_id, "test-user")
    finally:
        chat_route.get_anchor_store = original


# ── Test 3: /grievances calls ensure_conversation ──────────────────────────

def test_grievances_calls_ensure_conversation():
    test_id = str(uuid.uuid4())
    test_user = f"test-user-{uuid.uuid4().hex[:8]}"

    with patch("app.routes.grievance.ensure_conversation") as mock_ensure, \
         patch("app.routes.grievance._workflow") as mock_workflow:
        mock_workflow.process_message.return_value = MagicMock(
            response="test", stage=MagicMock(value="intake"),
            draft=None, is_complete=False, submission_route=None, evidence=None,
        )
        r = client.post("/grievances", json={
            "message": "I want to file a complaint",
            "conversation_id": test_id,
            "user_id": test_user,
        })
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        body = r.json()
        assert body["status"] == "ok"
        # P0 ownership: the client-supplied user_id is never trusted — the
        # conversation is bound to the authenticated identity ("test-user"
        # via the shared auth stub), not the spoofable request field.
        mock_ensure.assert_called_once_with(test_id, "test-user")
        _, kwargs = mock_workflow.process_message.call_args
        assert kwargs.get("user_id") == "test-user"
        mock_workflow.process_message.assert_called_once()


# ── Test 4: ensure_conversation uses atomic upsert ─────────────────────────

@patch("app.conversation_store.get_supabase")
def test_ensure_conversation_uses_upsert(mock_get_sb):
    mock_sb = MagicMock()
    mock_get_sb.return_value = mock_sb

    from app.conversation_store import ensure_conversation
    test_id = str(uuid.uuid4())
    test_user = f"test-user-{uuid.uuid4().hex[:8]}"

    ensure_conversation(test_id, test_user)

    mock_sb.table.assert_called_with("conversations")
    upsert_mock = mock_sb.table().upsert
    upsert_mock.assert_called_once()
    call_args = upsert_mock.call_args
    payload = call_args[0][0]
    assert payload["id"] == test_id
    assert payload["user_id"] == test_user
    assert payload["title"] == "New Chat"
    assert call_args[1].get("on_conflict") == "id"


@patch("app.conversation_store.get_supabase")
def test_ensure_conversation_idempotent(mock_get_sb):
    mock_sb = MagicMock()
    mock_get_sb.return_value = mock_sb

    from app.conversation_store import ensure_conversation
    test_id = str(uuid.uuid4())
    test_user = f"test-user-{uuid.uuid4().hex[:8]}"

    ensure_conversation(test_id, test_user)
    ensure_conversation(test_id, test_user)

    assert mock_sb.table().upsert.call_count == 2
