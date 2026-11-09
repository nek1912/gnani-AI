"""End-to-end pipeline test AGAINST REAL PROVIDERS (no respx mocking).

Validates the production-grade behavior the user asked for:
  - in-domain EN/HI -> grounded, cited answer from RAG
  - out-of-scope EN/HI -> LLM answers from its own knowledge (NOT abstain)

Runs against live Supabase + Gemini embeddings + Groq LLM. Intentionally NOT
collected in the default suite (named e2e_ and slow); run explicitly:
    pytest tests/e2e_real_pipeline.py -q -s
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_IN_DOMAIN_EN = "Who is eligible under PMFBY and what is the premium rate?"
_IN_DOMAIN_HI = "पीएमएफबीवाई के लिए कौन पात्र है और प्रीमियम दर क्या है?"
_OUT_EN = "What is the capital of France and why is it famous?"
_OUT_HI = "मौसम आज कैसा है और बारिश होगी क्या?"


def _post(question, language):
    return client.post("/chat", json={
        "question": question, "session_id": str(uuid.uuid4()),
        "language": language, "state": None})


def test_in_domain_english_returns_cited_answer():
    r = _post(_IN_DOMAIN_EN, "en")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["abstained"] is False
    assert body["language"] == "en"
    assert len(body["citations"]) >= 1
    assert body["confidence"] > 0
    print("\n[EN in-domain]\n", body["answer"][:400])


def test_in_domain_hindi_returns_cited_answer():
    r = _post(_IN_DOMAIN_HI, "hi")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["abstained"] is False
    assert body["language"] == "hi"
    assert len(body["citations"]) >= 1
    print("\n[HI in-domain]\n", body["answer"][:400])


def test_out_of_scope_english_gets_llm_answer():
    r = _post(_OUT_EN, "en")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["abstained"] is False           # NOT an abstention
    assert body["domain"] == "out_of_scope"
    assert body["citations"] == []             # no grounded citations
    assert len(body["answer"]) > 10
    print("\n[EN out-of-scope]\n", body["answer"][:400])


def test_out_of_scope_hindi_gets_llm_answer():
    r = _post(_OUT_HI, "hi")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["abstained"] is False
    assert body["domain"] == "out_of_scope"
    assert body["citations"] == []
    assert len(body["answer"]) > 10
    print("\n[HI out-of-scope]\n", body["answer"][:400])
