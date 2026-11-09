import uuid

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
PAYLOAD = {"question": "Who is eligible under PMFBY?", "session_id": str(uuid.uuid4()),
           "language": "en", "state": None}
EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
RPC_PATH = "/rest/v1/rpc/match_chunks"


@respx.mock
def test_answered_with_valid_citation(respx_mock):
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[{
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": "pmfby-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "Eligible farmers are covered.", "similarity": 0.72,
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
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "Farmers growing notified crops are eligible [chunk:aaaaaaaa]."}}]}))
    r = client.post("/chat", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is False and body["confidence"] > 0
    assert body["citations"][0]["title"] == "PMFBY FAQ"
    assert set(body) == {"answer", "language", "domain", "intent", "entities",
                          "confidence", "confidence_level", "citations",
                          "abstained", "speech_text", "speech_segments",
                          "follow_up_question", "mode", "conversation_id",
                          "referral"}
    # Speech copy must drop citation markers but keep the same wording.
    assert "[chunk:" not in body["speech_text"]
    assert "eligible" in body["speech_text"].lower()


@respx.mock
def test_answered_with_fullwidth_citation(respx_mock):
    """Groq often emits full-width 【ID】 markers; these must be normalised
    to [chunk:ID] and accepted when the ID matches retrieved evidence."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[{
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": "pmfby-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "Eligible farmers are covered.", "similarity": 0.72,
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
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "Farmers growing notified crops are eligible 【aaaaaaaa】."}}]}))
    r = client.post("/chat", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is False
    assert body["citations"][0]["title"] == "PMFBY FAQ"


@respx.mock
def test_fullwidth_citation_normalized_by_orchestrator(respx_mock):
    """Full-width 【ID】 markers are normalized to half-width by the orchestrator.
    The orchestrator auto-appends citations when the LLM omits them, but
    passes through answers that already contain citation markers."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[{
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": "pmfby-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "Eligible farmers are covered.", "similarity": 0.72,
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
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "Something about farmers 【aaaaaaaa】."}}]}))
    r = client.post("/chat", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is False
    assert "【" not in body["answer"]


@respx.mock
def test_abstains_when_retrieval_below_threshold(respx_mock):
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.01] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[]))
    r = client.post("/chat", json=PAYLOAD)
    body = r.json()
    assert body["abstained"] is True and body["citations"] == []
    assert body["answer"]  # safe message present


@respx.mock
def test_abstains_when_both_llms_fail(respx_mock):
    """Both LLMs down → safe abstention, not 500."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[{
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": "pmfby-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "Eligible farmers are covered.", "similarity": 0.72,
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
    # Both LLMs return 429
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"}))
    respx_mock.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"}))
    r = client.post("/chat", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is True
    assert body["citations"] == []
    assert body["answer"]  # safe message present


@respx.mock
def test_abstains_on_supabase_failure(respx_mock):
    """Supabase connection failure → safe abstention, not 503."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    # Supabase RPC returns500
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(500, json={"error": "internal error"}))
    r = client.post("/chat", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is True
    assert body["citations"] == []
    assert body["answer"]  # safe message present


@pytest.mark.parametrize("language", ["en", "hi", "gu", "mr", "bn"])
@respx.mock
def test_five_language_chat_accepts_language_and_emits_speech_text(respx_mock, language):
    """All five supported languages are accepted by /chat and the response
    carries a citation-free speech_text alongside the marker-bearing answer."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[{
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": "pmfby-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "Eligible farmers are covered.", "similarity": 0.72,
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
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "Farmers are eligible [chunk:aaaaaaaa]."}}]}))
    r = client.post("/chat", json={**PAYLOAD, "language": language,
                                   "ui_language_explicit": True})
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is False
    assert body["language"] == language
    # Each response carries speech segments keyed by text + language.
    assert isinstance(body["speech_segments"], list)
    assert all(set(s) >= {"text", "language"} for s in body["speech_segments"])
    # TTS-safe copy must exist and contain no citation markers.
    assert isinstance(body["speech_text"], str)
    assert "[chunk:" not in body["speech_text"]
    assert "Farmers are eligible" in body["speech_text"]


_RPC_ROWS = [{
    "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
    "stable_chunk_id": "pmfby-faq:p1:c0",
    "document_id": "dddd1111-2222-3333-4444-555555555555",
    "title": "PMFBY FAQ", "page": 1, "page_start": 1, "page_end": 1,
    "section": "Eligibility", "subsection": None, "clause": None,
    "content": "Eligible farmers are covered.", "similarity": 0.72,
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
    "domain": "pmfby", "jurisdiction": "central", "state": None}]


def _mock_pipeline(respx_mock):
    """Mirror the shared retrieval/LLM mock wiring used across this file."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=_RPC_ROWS))
    respx_mock.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {
            "content": "Farmers are eligible [chunk:aaaaaaaa]."}}]}))


@respx.mock
def test_response_language_from_explicit_in_text_request(respx_mock):
    """An embedded 'explain in Marathi' must resolve the response language to
    'mr' (via the resolver) and emit non-empty speech_segments with text+lang."""
    _mock_pipeline(respx_mock)
    # Default UI language 'en' must NOT override the text-embedded request.
    r = client.post("/chat", json={"question": "Who is eligible under PMFBY? explain in Marathi",
                                   "session_id": str(uuid.uuid4()),
                                   "language": "en", "state": None})
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is False
    assert body["language"] == "mr"
    assert isinstance(body["speech_segments"], list) and body["speech_segments"]
    # segment_speech emits {"text", "language"} per item.
    assert all(set(s) >= {"text", "language"} for s in body["speech_segments"])


_T5_SESS = "t5-sess"


@pytest.fixture
def _t5_session():
    from app.services.lang_memory import clear_session_language
    clear_session_language(_T5_SESS)
    yield
    clear_session_language(_T5_SESS)


@respx.mock
def test_ui_language_explicit_persists_across_turns(respx_mock, _t5_session):
    """First turn sets hi via ui_language_explicit; second turn with the same
    session but a default 'en' UI (ui_language_explicit=false) must NOT override
    the remembered Hindi session."""
    _mock_pipeline(respx_mock)
    first = client.post("/chat", json={"question": "Who is eligible under PMFBY?",
                                       "session_id": _T5_SESS, "language": "hi",
                                       "ui_language_explicit": True, "state": None})
    assert first.status_code == 200
    assert first.json()["language"] == "hi"
    # Simulate default-UI turn (frontend sends en but ui_language_explicit=false).
    second = client.post("/chat", json={"question": "Who is eligible under PMFBY?",
                                        "session_id": _T5_SESS, "language": "en",
                                        "ui_language_explicit": False, "state": None})
    assert second.status_code == 200
    assert second.json()["language"] == "hi"


@respx.mock
def test_abstain_emits_empty_speech_segments(respx_mock):
    """An abstention path returns speech_segments == [] (no read-aloud)."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.01] * 768}}))
    respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
        return_value=httpx.Response(200, json=[]))
    r = client.post("/chat", json={"question": "Who is eligible under PMFBY?",
                                   "session_id": str(uuid.uuid4()),
                                   "language": "en", "state": None})
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is True
    assert body["speech_segments"] == []
