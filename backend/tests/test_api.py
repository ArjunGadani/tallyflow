"""API surface (§11) via TestClient, injecting a stub store + fake LLM through
FastAPI dependency overrides."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.main import app, llm_dep, store_dep
from backend.store import LocalStore
from backend.tests.fakes import FakeLLM
from backend.tests.test_pipeline import CLASSIFY_INV, extract_json, pdf


@pytest.fixture
def client_factory():
    created = []

    def make(store, llm):
        app.dependency_overrides[store_dep] = lambda: store
        app.dependency_overrides[llm_dep] = lambda: llm
        created.append(True)
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_ingest_then_read_list_detail_flow_summary(client_factory):
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20")])
    client = client_factory(store, llm)

    files = {"file": ("inv.pdf", pdf("INVOICE INV-1 total 120"), "application/pdf")}
    r = client.post("/api/ingest", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["branch"] == "new" and body["status"] == "clean"
    iid = body["invoice"]["id"]
    assert len(body["flow"]) > 0

    assert any(i["id"] == iid for i in client.get("/api/invoices").json()["invoices"])
    assert client.get(f"/api/invoice/{iid}").json()["total"] == "120"
    assert len(client.get(f"/api/invoice/{iid}/flow").json()["flow"]) > 0
    assert client.get("/api/summary").json()["total_spend"] == "120"


def test_review_approve_moves_to_clean(client_factory):
    store = LocalStore(":memory:")
    iid = store.save_invoice({"doc_type": "invoice", "status": "needs_review",
                              "total": Decimal("50"), "base_total": Decimal("50"),
                              "is_invoice": True, "file_hash": "h1"})
    client = client_factory(store, FakeLLM([]))

    assert any(x["id"] == iid for x in client.get("/api/review-queue").json()["needs_review"])
    r = client.post(f"/api/invoice/{iid}/review", data={"action": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "clean"
    assert all(x["id"] != iid for x in client.get("/api/review-queue").json()["needs_review"])


def test_404_on_missing_invoice(client_factory):
    client = client_factory(LocalStore(":memory:"), FakeLLM([]))
    assert client.get("/api/invoice/nope").status_code == 404


def test_delete_invoice_endpoint(client_factory):
    store = LocalStore(":memory:")
    iid = store.save_invoice({"doc_type": "invoice", "status": "clean",
                              "total": Decimal("50"), "base_total": Decimal("50"),
                              "is_invoice": True, "file_hash": "h1"},
                             line_items=[{"description": "x", "amount": Decimal("1")}])
    client = client_factory(store, FakeLLM([]))
    assert client.delete(f"/api/invoice/{iid}").json()["status"] == "deleted"
    assert client.get(f"/api/invoice/{iid}").status_code == 404
    assert store.count_invoices() == 0 and store.count_line_items() == 0   # links gone
    assert client.delete("/api/invoice/nope").status_code == 404


def test_dismiss_dead_letter(client_factory):
    store = LocalStore(":memory:")
    did = store.add_dead_letter("x.pdf", "h", "boom", 4, "/tmp/x")
    client = client_factory(store, FakeLLM([]))
    r = client.post(f"/api/dead-letter/{did}/dismiss")
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert store.get_dead_letter(did) is None
    assert client.post("/api/dead-letter/nope/dismiss").status_code == 404


def test_retry_dead_letter_endpoint(client_factory, tmp_path):
    store = LocalStore(":memory:")
    payload = tmp_path / "inv.pdf"
    payload.write_bytes(pdf("INVOICE INV-1 total 120"))
    did = store.add_dead_letter("inv.pdf", "h", "transient", 4, str(payload))
    client = client_factory(store, FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20")]))
    r = client.post(f"/api/dead-letter/{did}/retry")
    assert r.status_code == 200 and r.json()["branch"] == "new"
    assert store.count_invoices() == 1
    assert store.get_dead_letter(did) is None
