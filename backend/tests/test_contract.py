"""Contract tests for POST /chat — verifies frozen API shape and Pydantic validation."""
import uuid

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
RPC_PATH = "/rest/v1/rpc/match_chunks"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

_SUCCESSFUL_CHUNKS = [
    {
        "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
        "stable_chunk_id": "pmfby-faq:p1:c0",
        "document_id": "dddd1111-2222-3333-4444-555555555555",
        "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
        "section": "Eligibility", "subsection": None, "clause": None,
        "content": "Eligible farmers are covered.", "similarity": 0.72,
        "source_url": "https://pmfby.gov.in/faq", "source_file": "pmfby.gov.in/faq",
        "domain": "pmfby", "jurisdiction": "central", "state": None,
    },
    {
        "chunk_id": "bbbbbbbb-5555-6666-7777-888888888888",
        "stable_chunk_id": "pmfby-guidelines:p4:c0",
        "document_id": "eeee1111-2222-3333-4444-555555555555",
        "title": "PMFBY Guidelines", "page": 4, "page_start": 4, "page_end": 4,
        "section": "Coverage", "subsection": None, "clause": None,
        "content": "Coverage extends to notified crops.", "similarity": 0.51,
        "source_url": "https://pmfby.gov.in/guidelines",
        "source_file": "pmfby.gov.in/guidelines",
        "domain": "pmfby", "jurisdiction": "central", "state": None,
    },
]

_GROQ_RESPONSE = httpx.Response(200, json={
    "choices": [{"message": {"content": "Farmers growing notified crops are eligible [chunk:aaaaaaaa]."}}]
})


def _valid_payload(**overrides) -> dict:
    base = {"question": "Who is eligible under PMFBY?",
            "session_id": str(uuid.uuid4()), "language": "en", "state": None}
    base.update(overrides)
    return base


def _assert_shape(body: dict):
    # P1-5: "referral" is an additive optional key (None when answered or
    # when no authority is confidently known). Old clients ignore it.
    assert set(body) == {"answer", "language", "domain", "intent", "entities",
                          "confidence", "confidence_level", "citations",
                          "abstained", "speech_text", "speech_segments",
                          "follow_up_question", "mode", "conversation_id",
                          "referral"}
    assert len(body) == 15
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["language"], str)
    assert body["language"] in ("en", "hi")
    assert isinstance(body["confidence"], float)
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["confidence_level"] in ("high", "moderate", "low", "none")
    assert isinstance(body["citations"], list)
    assert isinstance(body["abstained"], bool)
    assert body["follow_up_question"] is None
    assert body["referral"] is None or isinstance(body["referral"], dict)
    for c in body["citations"]:
        # New citation format includes source and source_label; old fields may be absent
        assert "chunk_id" in c
        assert "title" in c
        assert "url" in c
        assert c.get("source") in ("static", "web", None)


def _assert_abstained(body: dict):
    _assert_shape(body)
    assert body["abstained"] is True
    assert body["citations"] == []
    assert body["confidence"] == 0.0


def _assert_answered(body: dict):
    _assert_shape(body)
    assert body["abstained"] is False
    assert len(body["citations"]) >= 1
    for c in body["citations"]:
        assert "chunk_id" in c
        assert "title" in c
        assert "url" in c
        assert c.get("source") in ("static", "web", None)


def _mock_successful_route(respx_mock):
    respx_mock.post(EMBED_URL).mock(
        return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=_SUCCESSFUL_CHUNKS))
    respx_mock.post(GROQ_URL).mock(return_value=_GROQ_RESPONSE)


# ── Valid requests ──────────────────────────────────────────────────────

@respx.mock
def test_valid_english_request(respx_mock):
    _mock_successful_route(respx_mock)
    r = client.post("/chat", json=_valid_payload(language="en"))
    assert r.status_code == 200
    _assert_answered(r.json())


@respx.mock
def test_valid_hindi_request(respx_mock):
    hindi_question = "पीएमएफबीवाई के लिए कौन पात्र है?"
    respx_mock.post(EMBED_URL).mock(
        return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=_SUCCESSFUL_CHUNKS))
    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "पीएमएफबीवाई में अधिसूचित फसलें शामिल हैं [chunk:aaaaaaaa]."}}]}))
    r = client.post("/chat", json=_valid_payload(language="hi", question=hindi_question))
    assert r.status_code == 200
    body = r.json()
    _assert_answered(body)
    assert body["language"] == "hi"


# ── Validation errors (422) ────────────────────────────────────────────

def test_empty_question_returns_422():
    r = client.post("/chat", json={"question": "", "session_id": "s", "language": "en"})
    assert r.status_code == 422


def test_whitespace_only_question_returns_200_abstains():
    r = client.post("/chat", json={"question": "   ", "session_id": "s", "language": "en"})
    assert r.status_code == 200
    body = r.json()
    _assert_abstained(body)


def test_over_2000_chars_returns_422():
    r = client.post("/chat", json={
        "question": "a" * 2001, "session_id": "s", "language": "en"})
    assert r.status_code == 422


def test_missing_language_returns_422():
    r = client.post("/chat", json={
        "question": "test", "session_id": "s"})
    assert r.status_code == 422


def test_invalid_language_returns_422():
    r = client.post("/chat", json={
        "question": "test", "session_id": "s", "language": "fr"})
    assert r.status_code == 422


def test_missing_session_id_returns_422():
    r = client.post("/chat", json={"question": "test", "language": "en"})
    assert r.status_code == 422


# ── Edge cases ──────────────────────────────────────────────────────────

@respx.mock
def test_null_state_succeeds(respx_mock):
    _mock_successful_route(respx_mock)
    r = client.post("/chat", json=_valid_payload(state=None))
    assert r.status_code == 200
    _assert_shape(r.json())


@respx.mock
def test_extra_fields_ignored(respx_mock):
    _mock_successful_route(respx_mock)
    payload = _valid_payload()
    payload["boomer_field"] = "surprise"
    payload["nested"] = {"a": 1}
    r = client.post("/chat", json=payload)
    assert r.status_code == 200
    body = r.json()
    _assert_shape(body)
    assert "boomer_field" not in body
    assert "nested" not in body


@respx.mock
def test_abstained_response_shape(respx_mock):
    respx_mock.post(EMBED_URL).mock(
        return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[]))
    r = client.post("/chat", json=_valid_payload())
    assert r.status_code == 200
    _assert_abstained(r.json())


# ── Invariant: answer is always non-empty ───────────────────────────────

@respx.mock
def test_answer_always_non_empty(respx_mock):
    _mock_successful_route(respx_mock)
    r = client.post("/chat", json=_valid_payload())
    body = r.json()
    assert len(body["answer"].strip()) > 0


# ── Invariant: confidence in [0,1] for answered ────────────────────────

@respx.mock
def test_confidence_in_range(respx_mock):
    _mock_successful_route(respx_mock)
    r = client.post("/chat", json=_valid_payload())
    body = r.json()
    assert 0.0 <= body["confidence"] <= 1.0
