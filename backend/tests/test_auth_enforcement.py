"""Auth-enforcement contract tests (P0).

Every mutation-capable and quota-burning endpoint must reject callers
without a valid Clerk JWT with 401 {"detail": "Not authenticated"}.

The shared conftest fixture stubs require_auth for all OTHER tests so
they can exercise retrieval/generation logic; THESE tests explicitly
clear that stub to verify the real gate.
"""
import uuid

from fastapi.testclient import TestClient

from app.auth import require_auth
from app.main import app

client = TestClient(app)


def test_chat_requires_auth():
    app.dependency_overrides.clear()
    try:
        r = client.post("/chat", json={
            "question": "What is PMFBY?",
            "session_id": str(uuid.uuid4()),
            "language": "en",
        })
        assert r.status_code == 401
        assert r.json() == {"detail": "Not authenticated"}
    finally:
        app.dependency_overrides[require_auth] = lambda: "test-user"


def test_chat_stream_requires_auth():
    app.dependency_overrides.clear()
    try:
        r = client.post("/chat/stream", json={
            "question": "What is PMFBY?",
            "session_id": str(uuid.uuid4()),
            "language": "en",
        })
        assert r.status_code == 401
    finally:
        app.dependency_overrides[require_auth] = lambda: "test-user"


def test_grievance_write_requires_auth():
    app.dependency_overrides.clear()
    try:
        r = client.post("/grievances", json={
            "message": "Waterlogging in my street",
            "conversation_id": str(uuid.uuid4()),
            "user_id": "someone-else",
        })
        assert r.status_code == 401
        assert r.json() == {"detail": "Not authenticated"}
    finally:
        app.dependency_overrides[require_auth] = lambda: "test-user"


def test_grievance_fields_requires_auth():
    app.dependency_overrides.clear()
    try:
        r = client.get("/grievances/conv-123/fields?language=en")
        assert r.status_code == 401
    finally:
        app.dependency_overrides[require_auth] = lambda: "test-user"


def test_voice_transcribe_requires_auth():
    app.dependency_overrides.clear()
    try:
        r = client.post("/voice/transcribe", json={"audio": "dGVzdA==", "language": "en"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides[require_auth] = lambda: "test-user"


def test_voice_speak_requires_auth():
    app.dependency_overrides.clear()
    try:
        r = client.post("/voice/speak", json={"text": "Hello", "language": "en"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides[require_auth] = lambda: "test-user"
