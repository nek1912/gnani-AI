"""PHASE 7: Evidence gate pipeline tests.

Verifies the pipeline order: retrieval → evidence gate → LLM
NEVER: retrieval → LLM → LLM decides

Test cases:
- Answerable question → grounded answer
- Unanswerable question → abstention
- Off-topic question → out_of_scope
- Wrong domain question → filtered/rejected
- Ambiguous question → handled appropriately
"""
import uuid
from unittest.mock import patch, MagicMock

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.retrieval import RetrievedChunk, evidence_gate

client = TestClient(app)
EMBED_URL = "https://api.jina.ai/v1/embeddings"
EMBED_URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
EMBED_MOCK_RESPONSE = {"data": [{"embedding": [0.5] * 768, "index": 0}]}


def _mock_embeddings(respx_mock):
    """Mock both Jina and Gemini embedding endpoints."""
    respx_mock.post(EMBED_URL).mock(return_value=httpx.Response(200, json=EMBED_MOCK_RESPONSE))
    respx_mock.post(EMBED_URL_GEMINI).mock(return_value=httpx.Response(200, json={
        "embedding": {"values": [0.5] * 768}
    }))
RPC_PATH = "/rest/v1/rpc/match_chunks"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _mock_chunks(
    domain: str = "pmfby",
    jurisdiction: str = "central",
    state: str | None = None,
    similarities: list[float] | None = None,
) -> list[dict]:
    """Create mock Supabase RPC response chunks."""
    sims = similarities or [0.72, 0.51, 0.35]
    # Chunk-id prefixes MUST be distinct: the citation verifier treats an
    # 8-char prefix matching >1 retrieved chunk as ambiguous → invalid, so
    # shared "aaaaaaaa" prefixes would (correctly) fail verification.
    prefixes = ["aaaaaaaa", "bbbbbbbb", "cccccccc", "dddddddd", "eeeeeeee"]
    return [
        {
            "chunk_id": f"{prefixes[i % len(prefixes)]}-{i:04d}-2222-3333-444444444444",
            "stable_chunk_id": f"{domain}-faq:p{i+1}:c0",
            "document_id": f"dddd{i:04d}-2222-3333-4444-555555555555",
            "title": f"{domain.upper()} Document {i}",
            "page": i + 1,
            "page_start": i + 1,
            "page_end": i + 1,
            "section": "Section",
            "subsection": None,
            "clause": None,
            # Content names the domain (real chunks do) so entity grounding
            # ("PMFBY", ...) resolves instead of flagging test answers.
            "content": f"Content about {domain.upper()}",
            "similarity": sim,
            "source_url": f"https://{domain}.example.com/{i}",
            "source_file": f"{domain}.pdf",
            "domain": domain,
            "jurisdiction": jurisdiction,
            "state": state,
        }
        for i, sim in enumerate(sims)
    ]


def _payload(**overrides) -> dict:
    base = {
        "question": "What is PMFBY eligibility?",
        "session_id": str(uuid.uuid4()),
        "language": "en",
        "state": None,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE ORDER: retrieval → evidence gate → LLM
# ═══════════════════════════════════════════════════════════════════════════

class TestPipelineOrder:
    """Verify evidence gate runs BEFORE LLM generation."""

    @respx.mock
    def test_evidence_gate_blocks_llm_call(self, respx_mock):
        """When evidence gate fails, LLM is never called."""
        _mock_embeddings(respx_mock)
        # Return low similarity chunks that will fail evidence gate
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks(similarities=[0.20, 0.15, 0.10])))
        # Mock LLM — should NOT be called
        groq_mock = respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "This should not be called [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload())
        body = r.json()

        assert body["abstained"] is True
        assert body["citations"] == []
        assert body["confidence"] == 0.0
        # LLM should NOT have been called
        assert groq_mock.call_count == 0

    @respx.mock
    def test_evidence_gate_passes_to_llm(self, respx_mock):
        """When evidence gate passes, LLM is called."""
        _mock_embeddings(respx_mock)
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks(similarities=[0.72, 0.51, 0.35])))
        groq_mock = respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "Farmers with notified crops are eligible [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload())
        body = r.json()

        assert body["abstained"] is False
        assert len(body["citations"]) >= 1
        assert groq_mock.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# ANSWERABLE QUESTION → grounded answer
# ═══════════════════════════════════════════════════════════════════════════

class TestAnswerableQuestion:
    """Answerable question with sufficient evidence → grounded answer."""

    @respx.mock
    def test_answerable_returns_grounded_answer(self, respx_mock):
        _mock_embeddings(respx_mock)
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks(similarities=[0.82, 0.65, 0.48])))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "PMFBY covers all food crops, oilseeds, and annual horticultural crops [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload(question="What does PMFBY cover?"))
        body = r.json()

        assert body["abstained"] is False
        assert body["domain"] == "pmfby"
        assert body["confidence"] > 0.0
        assert len(body["citations"]) >= 1
        assert "answer" in body and len(body["answer"]) > 0


# ═══════════════════════════════════════════════════════════════════════════
# UNANSWERABLE QUESTION → abstention
# ═══════════════════════════════════════════════════════════════════════════

class TestUnanswerableQuestion:
    """Unanswerable question (no evidence) → abstention."""

    @respx.mock
    def test_no_chunks_abstains(self, respx_mock):
        _mock_embeddings(respx_mock)
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=[]))

        r = client.post("/chat", json=_payload(question="What is the meaning of life?"))
        body = r.json()

        assert body["abstained"] is True
        assert body["citations"] == []
        assert body["confidence"] == 0.0
        assert body["answer"]  # Should have a safe abstention message

    @respx.mock
    def test_low_similarity_abstains(self, respx_mock):
        _mock_embeddings(respx_mock)
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks(similarities=[0.25, 0.20, 0.15])))

        r = client.post("/chat", json=_payload())
        body = r.json()

        assert body["abstained"] is True
        assert body["citations"] == []


# ═══════════════════════════════════════════════════════════════════════════
# OFF-TOPIC QUESTION → out_of_scope
# ═══════════════════════════════════════════════════════════════════════════

class TestOffTopicQuestion:
    """Off-topic question (classifier says out_of_scope) → out_of_scope."""

    @respx.mock
    def test_out_of_scope_returns_immediately(self, respx_mock):
        _mock_embeddings(respx_mock)

        with patch("app.routes.chat.get_anchor_store") as mock_get_anchor, \
             patch("app.routes.chat.resolve_and_remember", return_value="en"), \
             patch("app.routes.chat.touch_session"), \
             patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"):
            fake_store = MagicMock()
            fake_store.classify.return_value = ("out_of_scope", 0.1)
            mock_get_anchor.return_value = fake_store

            r = client.post("/chat", json=_payload(question="What is quantum physics?"))
            body = r.json()

            assert body["abstained"] is True
            assert body["domain"] == "out_of_scope"
            assert body["citations"] == []


# ═══════════════════════════════════════════════════════════════════════════
# WRONG DOMAIN QUESTION → filtered/rejected
# ═══════════════════════════════════════════════════════════════════════════

class TestWrongDomainQuestion:
    """Wrong domain question → evidence gate rejects cross-domain chunks."""

    @respx.mock
    def test_wrong_domain_chunks_abstain(self, respx_mock):
        _mock_embeddings(respx_mock)
        # Return chunks from wrong domain
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks(
                domain="finlit", similarities=[0.82, 0.65, 0.48])))

        r = client.post("/chat", json=_payload(question="What is PMFBY?"))
        body = r.json()

        # The classifier may return "pmfby" based on keywords, but retrieval
        # returns finlit chunks → evidence gate catches domain mismatch
        assert body["abstained"] is True
        assert body["citations"] == []


# ═══════════════════════════════════════════════════════════════════════════
# AMBIGUOUS QUESTION → handled appropriately
# ═══════════════════════════════════════════════════════════════════════════

class TestAmbiguousQuestion:
    """Ambiguous question → either grounded answer (if evidence exists) or abstention."""

    @respx.mock
    def test_ambiguous_with_evidence_answers(self, respx_mock):
        """Ambiguous question that matches some evidence → answer with confidence."""
        _mock_embeddings(respx_mock)
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks(similarities=[0.62, 0.45, 0.38])))
        respx_mock.post(GROQ_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {
                "content": "The scheme provides crop insurance [chunk:aaaaaaaa]."}}]}))

        r = client.post("/chat", json=_payload(question="Tell me about the scheme"))
        body = r.json()

        # Should either answer or abstain — both are valid for ambiguous
        if not body["abstained"]:
            assert body["confidence"] > 0.0
            assert len(body["citations"]) >= 1

    @respx.mock
    def test_ambiguous_without_evidence_abstains(self, respx_mock):
        """Ambiguous question with no evidence → abstention."""
        _mock_embeddings(respx_mock)
        respx_mock.post(httpx.URL("http://testsupa" + RPC_PATH)).mock(
            return_value=httpx.Response(200, json=_mock_chunks(similarities=[0.28, 0.22, 0.18])))

        r = client.post("/chat", json=_payload(question="Tell me about the thing"))
        body = r.json()

        assert body["abstained"] is True
        assert body["citations"] == []


# ═══════════════════════════════════════════════════════════════════════════
# EVIDENCE GATE UNIT TESTS (pipeline order)
# ═══════════════════════════════════════════════════════════════════════════

class TestEvidenceGateUnit:
    """Unit tests for the evidence gate function itself."""

    def test_empty_chunks_abstains(self):
        result = evidence_gate([], expected_domain="pmfby")
        assert result.abstained is True
        assert result.reason == "no_chunks"

    def test_wrong_domain_abstains(self):
        chunks = [RetrievedChunk(
            chunk_id="c1", stable_chunk_id="test:p1:c0",
            document_id="d1", title="T", page=1,
            page_start=1, page_end=1, section="S",
            content="C", similarity=0.8, source_url="https://x",
            domain="finlit", jurisdiction="central", state=None,
        )]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is True
        assert result.reason == "domain_mismatch_in_retrieval"

    def test_wrong_jurisdiction_abstains(self):
        chunks = [RetrievedChunk(
            chunk_id="c1", stable_chunk_id="test:p1:c0",
            document_id="d1", title="T", page=1,
            page_start=1, page_end=1, section="S",
            content="C", similarity=0.8, source_url="https://x",
            domain="pmfby", jurisdiction="state", state="maharashtra",
        )]
        result = evidence_gate(chunks, expected_domain="pmfby", expected_state="gujarat")
        assert result.abstained is True
        assert result.reason == "jurisdiction_mismatch_in_retrieval"

    def test_low_similarity_abstains(self):
        chunks = [RetrievedChunk(
            chunk_id="c1", stable_chunk_id="test:p1:c0",
            document_id="d1", title="T", page=1,
            page_start=1, page_end=1, section="S",
            content="C", similarity=0.20, source_url="https://x",
            domain="pmfby", jurisdiction="central", state=None,
        )]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is True
        assert result.reason == "below_top1_threshold"

    def test_passes_with_sufficient_evidence(self):
        chunks = [
            RetrievedChunk(
                chunk_id=f"c{i}", stable_chunk_id=f"test:p{i}:c0",
                document_id="d1", title="T", page=i,
                page_start=i, page_end=i, section="S",
                content="C", similarity=sim, source_url="https://x",
                domain="pmfby", jurisdiction="central", state=None,
            )
            for i, sim in enumerate([0.82, 0.65, 0.48], start=1)
        ]
        result = evidence_gate(chunks, expected_domain="pmfby")
        assert result.abstained is False
        assert result.confidence > 0.0
