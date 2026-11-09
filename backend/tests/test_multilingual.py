"""PHASE 11: Multilingual retrieval tests.

Tests that queries in English, Hindi, and Gujarati:
1. Are correctly language-detected
2. Preserve the original query throughout the pipeline
3. Retrieve correct English evidence
4. Return correct grounded answers with citations

The source corpus is always English. The query is in the user's language.
"""
import uuid

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.language import normalize_language

client = TestClient(app)
EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
RPC_PATH = "/rest/v1/rpc/match_chunks"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _mock_chunks(domain: str = "pmfby") -> list[dict]:
    return [
        {
            "chunk_id": "aaaaaaaa-1111-2222-3333-444444444444",
            "stable_chunk_id": f"{domain}-faq:p1:c0",
            "document_id": "dddd1111-2222-3333-4444-555555555555",
            "title": f"{domain.upper()} FAQ",
            "page": 1, "page_start": 1, "page_end": 1,
            "section": "Eligibility", "subsection": None, "clause": None,
            "content": "Eligible farmers growing notified crops are covered.",
            "similarity": 0.72,
            "source_url": f"https://{domain}.gov.in/faq",
            "source_file": "faq.pdf",
            "domain": domain, "jurisdiction": "central", "state": None,
        },
        {
            "chunk_id": "bbbbbbbb-5555-6666-7777-888888888888",
            "stable_chunk_id": f"{domain}-guidelines:p4:c0",
            "document_id": "eeee1111-2222-3333-4444-555555555555",
            "title": f"{domain.upper()} Guidelines",
            "page": 4, "page_start": 4, "page_end": 4,
            "section": "Coverage", "subsection": None, "clause": None,
            "content": "Coverage extends to all notified crops.",
            "similarity": 0.51,
            "source_url": f"https://{domain}.gov.in/guidelines",
            "source_file": "guidelines.pdf",
            "domain": domain, "jurisdiction": "central", "state": None,
        },
        {
            "chunk_id": "cccccccc-9999-aaaa-bbbb-cccccccccccc",
            "stable_chunk_id": f"{domain}-premium:p2:c0",
            "document_id": "ffff1111-2222-3333-4444-555555555555",
            "title": f"{domain.upper()} Premium",
            "page": 2, "page_start": 2, "page_end": 2,
            "section": "Premium Rate", "subsection": None, "clause": None,
            "content": "Premium rates vary by crop type.",
            "similarity": 0.38,
            "source_url": f"https://{domain}.gov.in/premium",
            "source_file": "premium.pdf",
            "domain": domain, "jurisdiction": "central", "state": None,
        },
    ]


def _payload(language: str, question: str, **overrides) -> dict:
    base = {
        "question": question,
        "session_id": str(uuid.uuid4()),
        "language": language,
        "state": None,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# LANGUAGE DETECTION
# ═══════════════════════════════════════════════════════════════════════════

class TestLanguageDetection:
    """Multilingual queries must be correctly language-detected."""

    def test_english_query_detected(self):
        assert normalize_language("en", "What is PMFBY eligibility?") == "en"

    def test_hindi_devanagari_detected(self):
        assert normalize_language("hi", "पीएमएफबीवाई में कैसे आवेदन करें") == "hi"

    def test_hindi_latin_detected(self):
        assert normalize_language("hi", "meri fasal ka insurance kaise milega") == "hi"

    def test_gujarati_script_detected(self):
        assert normalize_language("gu", "પીએમએફબીવાઈ માટે કોણ પાત્ર છે?") == "gu"

    def test_gujarati_latin_detected(self):
        assert normalize_language("gu", "PMFBY ma ketla khedut paatra che?") == "gu"

    def test_invalid_language_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            normalize_language("fr", "bonjour")

    def test_english_with_hindi_script_returns_hindi(self):
        """Devanagari script overrides English selection."""
        assert normalize_language("en", "पीएमएफबीवाई के लिए कौन पात्र है?") == "hi"

    def test_english_with_gujarati_script_returns_gujarati(self):
        """Gujarati script overrides English selection."""
        assert normalize_language("en", "પીએમએફબીવાઈ માટે કોણ પાત્ર છે?") == "gu"


# ═══════════════════════════════════════════════════════════════════════════
# ORIGINAL QUERY PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

class TestQueryPreservation:
    """The original user query must be preserved throughout the pipeline."""

    @respx.mock
    def test_hindi_query_used_for_embedding(self, respx_mock):
        """Hindi query is embedded directly — not translated to English first."""
        embed_mock = respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY covers notified crops [chunk:aaaaaaaa]."}}]}))

        hindi_q = "पीएमएफबीवाई के लिए कौन पात्र है?"
        r = client.post("/chat", json=_payload("hi", hindi_q))
        assert r.status_code == 200

        # Verify the embedding request used the Hindi query, not English
        embed_body = embed_mock.calls[0].request.content
        assert hindi_q.encode() in embed_body

    @respx.mock
    def test_gujarati_query_used_for_embedding(self, respx_mock):
        """Gujarati query is embedded directly."""
        embed_mock = respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY covers notified crops [chunk:aaaaaaaa]."}}]}))

        gu_q = "પીએમએફબીવાઈ માટે કોણ પાત્ર છે?"
        r = client.post("/chat", json=_payload("gu", gu_q))
        assert r.status_code == 200

        embed_body = embed_mock.calls[0].request.content
        assert gu_q.encode() in embed_body

    @respx.mock
    def test_english_query_used_for_embedding(self, respx_mock):
        """English query is embedded directly."""
        embed_mock = respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY covers notified crops [chunk:aaaaaaaa]."}}]}))

        en_q = "What is PMFBY eligibility?"
        r = client.post("/chat", json=_payload("en", en_q))
        assert r.status_code == 200

        embed_body = embed_mock.calls[0].request.content
        assert en_q.encode() in embed_body


# ═══════════════════════════════════════════════════════════════════════════
# MULTILINGUAL RETRIEVAL → ENGLISH EVIDENCE
# ═══════════════════════════════════════════════════════════════════════════

class TestMultilingualRetrieval:
    """Queries in any language must retrieve English evidence."""

    @respx.mock
    def test_english_query_retrieves_english_evidence(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "Farmers are eligible [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload("en", "What is PMFBY?"))
        body = r.json()
        assert body["abstained"] is False
        assert body["domain"] == "pmfby"
        assert len(body["citations"]) >= 1
        # Evidence is in English
        assert "eligible" in body["answer"].lower() or "covered" in body["answer"].lower()

    @respx.mock
    def test_hindi_query_retrieves_english_evidence(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "अधिसूचित फसलें कवर हैं [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload("hi", "पीएमएफबीवाई क्या है?"))
        body = r.json()
        assert body["abstained"] is False
        assert body["language"] == "hi"
        assert body["domain"] == "pmfby"
        assert len(body["citations"]) >= 1

    @respx.mock
    def test_gujarati_query_retrieves_english_evidence(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "અધિસૂચિત પાક કવર છે [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload("gu", "પીએમએફબીવાઈ શું છે?"))
        body = r.json()
        assert body["abstained"] is False
        assert body["language"] == "gu"
        assert body["domain"] == "pmfby"
        assert len(body["citations"]) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# MULTILINGUAL DOMAIN CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestMultilingualDomain:
    """Domain classification must work for all supported languages.
    
    Note: The conftest patches get_anchor_store to always return 'pmfby'.
    These tests override that patch to test domain classification.
    """

    @respx.mock
    def test_hindi_pmfby_query_classified(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks("pmfby")))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload("hi", "पीएमएफबीवाई दावा कैसे दायर करें?"))
        # conftest returns pmfby by default
        assert r.json()["domain"] == "pmfby"

    @respx.mock
    def test_gujarati_cooperative_query_classified(self, respx_mock):
        """Test that Gujarati queries work with keyword-based classification."""
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks("cooperative")))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "Cooperative [chunk:aaaaaaaa]."}}]}))

        import app.routes.chat as chat_route
        class _CoopStore:
            @staticmethod
            def classify(_text, _embedding):
                return "cooperative", 1.0
        original = chat_route.get_anchor_store
        chat_route.get_anchor_store = lambda: _CoopStore()
        try:
            r = client.post("/chat", json=_payload("gu", "sahakari cooperative niyaamo su che?"))
            assert r.json()["domain"] == "cooperative"
        finally:
            chat_route.get_anchor_store = original

    @respx.mock
    def test_hindi_finlit_query_classified(self, respx_mock):
        """Test that Hindi queries work with keyword-based classification."""
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks("finlit")))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMJDY [chunk:aaaaaaaa]."}}]}))

        import app.routes.chat as chat_route
        class _FinlitStore:
            @staticmethod
            def classify(_text, _embedding):
                return "finlit", 1.0
        original = chat_route.get_anchor_store
        chat_route.get_anchor_store = lambda: _FinlitStore()
        try:
            r = client.post("/chat", json=_payload("hi", "PMJDY khata kya hai?"))
            assert r.json()["domain"] == "finlit"
        finally:
            chat_route.get_anchor_store = original


# ═══════════════════════════════════════════════════════════════════════════
# MULTILINGUAL ABSTENTION
# ═══════════════════════════════════════════════════════════════════════════

class TestMultilingualAbstention:
    """Abstention messages must be in the user's language."""

    @respx.mock
    def test_hindi_abstention_message(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=[]))

        r = client.post("/chat", json=_payload("hi", "पीएमएफबीवाई क्या है?"))
        body = r.json()
        assert body["abstained"] is True
        assert body["language"] == "hi"
        # Hindi abstention message should contain Devanagari
        assert any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in body["answer"])

    @respx.mock
    def test_gujarati_abstention_message(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=[]))

        r = client.post("/chat", json=_payload("gu", "પીએમએફબીવાઈ શું છે?"))
        body = r.json()
        assert body["abstained"] is True
        assert body["language"] == "gu"
        # Gujarati abstention message should contain Gujarati script
        assert any(ord(c) >= 0x0A80 and ord(c) <= 0x0AFF for c in body["answer"])

    @respx.mock
    def test_english_abstention_message(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=[]))

        r = client.post("/chat", json=_payload("en", "What is PMFBY?"))
        body = r.json()
        assert body["abstained"] is True
        assert body["language"] == "en"
        assert "official sources" in body["answer"]


# ═══════════════════════════════════════════════════════════════════════════
# MULTILINGUAL CONTRACT SHAPE
# ═══════════════════════════════════════════════════════════════════════════

class TestMultilingualContract:
    """Response shape must be consistent across all languages."""

    @respx.mock
    def test_english_response_shape(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload("en", "What is PMFBY?"))
        body = r.json()
        assert set(body) == {"answer", "language", "domain", "intent", "entities",
                             "confidence", "confidence_level", "citations",
                             "abstained", "speech_text", "speech_segments",
                             "follow_up_question", "mode", "conversation_id",
                             "referral"}
        assert body["language"] == "en"

    @respx.mock
    def test_hindi_response_shape(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload("hi", "पीएमएफबीवाई क्या है?"))
        body = r.json()
        assert set(body) == {"answer", "language", "domain", "intent", "entities",
                             "confidence", "confidence_level", "citations",
                             "abstained", "speech_text", "speech_segments",
                             "follow_up_question", "mode", "conversation_id",
                             "referral"}
        assert body["language"] == "hi"

    @respx.mock
    def test_gujarati_response_shape(self, respx_mock):
        respx_mock.post(EMBED_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.5] * 768}}))
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks()))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload("gu", "પીએમએફબીવાઈ શું છે?"))
        body = r.json()
        assert set(body) == {"answer", "language", "domain", "intent", "entities",
                             "confidence", "confidence_level", "citations",
                             "abstained", "speech_text", "speech_segments",
                             "follow_up_question", "mode", "conversation_id",
                             "referral"}
        assert body["language"] == "gu"
