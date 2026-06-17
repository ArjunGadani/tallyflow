"""POST /api/chat surface via TestClient + dependency overrides (§6)."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.llm import LLMError
from backend.main import app, llm_dep, store_dep
from backend.store import LocalStore
from backend.tests.fakes import FakeChatLLM, RaisingLLM, text_turn, tool_turn


@pytest.fixture
def client_factory():
    def make(store, llm):
        app.dependency_overrides[store_dep] = lambda: store
        app.dependency_overrides[llm_dep] = lambda: llm
        return TestClient(app)
    yield make
    app.dependency_overrides.clear()


def _seed():
    st = LocalStore(":memory:")
    vid = st.upsert_vendor("Globex", default_category="Cloud")
    st.save_invoice({"vendor_id": vid, "doc_type": "invoice", "status": "clean",
                     "category": "Cloud", "total": Decimal("100"), "base_total": Decimal("100"),
                     "currency": "GBP", "is_invoice": True, "file_hash": "h1"})
    return st


def test_chat_grounded_answer(client_factory):
    llm = FakeChatLLM([tool_turn([("get_expense_summary", {})]),
                       text_turn("You spent GBP 100 across 1 invoice.")])
    client = client_factory(_seed(), llm)
    r = client.post("/api/chat", json={"message": "what did we spend?"})
    assert r.status_code == 200
    body = r.json()
    assert "100" in body["answer"]
    assert body["grounding_ok"] is True
    assert body["conversation_id"]
    assert body["result"]["kind"] == "summary"
    assert body["result"]["data"]["total_spend"] == "100"  # exact string, not float


def test_chat_empty_message_400(client_factory):
    client = client_factory(_seed(), FakeChatLLM([]))
    r = client.post("/api/chat", json={"message": "   "})
    assert r.status_code == 400


def test_chat_llm_error_503(client_factory):
    client = client_factory(_seed(), RaisingLLM(LLMError("down", transient=False)))
    r = client.post("/api/chat", json={"message": "spend?"})
    assert r.status_code == 503
    assert r.json()["answer"] is None
