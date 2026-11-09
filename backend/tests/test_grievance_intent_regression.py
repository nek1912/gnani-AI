import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def chat(question, language="en"):
    resp = client.post("/chat", json={"question": question, "session_id": "test123", "language": language})
    return resp.json()

@pytest.mark.parametrize("msg, lang", [
    ("I want to file a complaint about Unallocated Garbage in my area", "en"),
    ("I want to complain about garbage not being collected", "en"),
    ("There has been garbage piling up near my house", "en"),
    ("I need to report a sanitation problem", "en"),
    ("મારે મારા વિસ્તારમાં કચરા સંબંધિત ફરિયાદ કરવાની છે", "gu"),
    ("मैं अपने क्षेत्र में कचरा समस्या की रिपोर्ट करना चाहता हूँ", "hi"),
])
def test_grievance_intent(msg, lang):
    result = chat(msg, language=lang)
    # Must not be abstained
    assert not result.get("abstained", True)
    # Must route to grievance domain with GRIEVANCE intent
    assert result["domain"] == "grievance"
    assert result["intent"] == "GRIEVANCE"
    # Must contain a grievance payload (not just the key)
    assert isinstance(result.get("grievance"), dict)

def test_non_grievance_question():
    result = chat("What is the capital of Gujarat?", language="en")
    # Should be out-of-scope or normal answer, not grievance
    assert result.get("domain") != "grievance"
    assert result.get("abstained") is not None
