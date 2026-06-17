"""/healthz must be a pure 200 with no DB/LLM dependency (§11) — it backs the
Cloud Run startup probe and the dashboard cold-start poll, so it has to answer
even with zero creds configured."""
from fastapi.testclient import TestClient

from backend.main import app


def test_healthz_is_200_and_ok():
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_healthz_works_without_any_creds(monkeypatch):
    # No Supabase, no Groq — startup probe must still pass.
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
