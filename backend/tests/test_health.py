from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_health_providers_shape():
    r = client.get("/health/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["groq"] == "configured" and body["bhashini"] == "stub"
