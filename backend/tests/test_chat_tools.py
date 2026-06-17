"""Deterministic tool executors — the chatbot's only data source (§7.2)."""
from decimal import Decimal

import pytest

from backend.chat_tools import execute
from backend.store import LocalStore


@pytest.fixture
def store():
    st = LocalStore(":memory:")
    vid = st.upsert_vendor("Globex", default_category="Cloud")
    st.save_invoice({"vendor_id": vid, "doc_type": "invoice", "status": "clean",
                     "invoice_number": "INV-1001", "invoice_date": "2026-05-10",
                     "category": "Cloud", "total": Decimal("100"), "base_total": Decimal("100"),
                     "currency": "GBP", "is_invoice": True, "file_hash": "h1"})
    st.save_invoice({"vendor_id": vid, "doc_type": "credit_note", "status": "clean",
                     "invoice_number": "CN-1", "invoice_date": "2026-05-12",
                     "category": "Cloud", "total": Decimal("20"), "base_total": Decimal("20"),
                     "currency": "GBP", "is_invoice": True, "file_hash": "h2"})
    st.save_invoice({"vendor_id": vid, "doc_type": "invoice", "status": "needs_review",
                     "invoice_number": "INV-1002", "invoice_date": "2026-05-15",
                     "total": Decimal("50"), "base_total": Decimal("50"),
                     "currency": "GBP", "is_invoice": True, "file_hash": "h3"})
    return st


def test_summary_subtracts_credits_and_excludes_pending(store):
    r = execute("get_expense_summary", {}, store)
    assert r["source"] == "summary"
    assert r["total_spend"] == Decimal("80")          # 100 clean - 20 credit
    assert r["credits_total"] == Decimal("20")
    assert r["pending_review_excluded"] == Decimal("50")
    assert r["needs_review_count"] == 1
    assert r["invoices_counted"] == 1


def test_summary_rejects_bad_date(store):
    r = execute("get_expense_summary", {"date_from": "2026-13-99"}, store)
    assert r["error"] == "bad_date"


def test_summary_rejects_inverted_range(store):
    # df > dt would silently return an empty window presented as authoritative zero.
    r = execute("get_expense_summary", {"date_from": "2026-12-01", "date_to": "2026-01-01"}, store)
    assert r["error"] == "bad_range"


def test_list_invoices_rejects_inverted_range(store):
    r = execute("list_invoices", {"date_from": "2026-12-01", "date_to": "2026-01-01"}, store)
    assert r["error"] == "bad_range"


def test_failed_tool_does_not_leak_exception_text(store):
    # A tool that blows up returns a generic error with NO raw exception detail.
    class Boom:
        def list_vendors(self):
            raise RuntimeError("secret SQL: SELECT * FROM users")
    r = execute("list_vendors", {}, Boom())
    assert r["error"] == "tool_failed"
    assert "detail" not in r and "secret" not in str(r)


def test_list_invoices_clamps_and_flags_truncated(store):
    r = execute("list_invoices", {"limit": 1}, store)
    assert r["count"] == 1 and r["truncated"] is True
    assert set(r["invoices"][0]) >= {"id", "vendor_name", "invoice_number", "total", "status"}


def test_list_invoices_rejects_bad_status(store):
    r = execute("list_invoices", {"status": "paid"}, store)
    assert r["error"] == "bad_status"


def test_get_invoice_not_found(store):
    r = execute("get_invoice", {"invoice_id": "nope"}, store)
    assert r["error"] == "not_found"


def test_get_invoice_hides_files(store):
    iid = store.list_invoices()[0]["id"]
    r = execute("get_invoice", {"invoice_id": iid}, store)
    assert "files" not in r and r["source"] == f"invoice:{iid}"


def test_search_by_vendor_matches_fuzzily(store):
    r = execute("search_invoices_by_vendor", {"vendor_query": "globex inc"}, store)
    assert r["matched"] is True and r["vendor"]["canonical_name"] == "Globex"
    assert r["count"] >= 1


def test_search_by_vendor_unmatched_lists_known(store):
    r = execute("search_invoices_by_vendor", {"vendor_query": "Wayne Enterprises"}, store)
    assert r["matched"] is False and "Globex" in r["known_vendors"]


def test_resolve_date_range_tool(store):
    r = execute("resolve_date_range", {"phrase": "last_month"}, store)
    assert r["source"] == "daterange" and r["date_from"].endswith("-01")


def test_review_counts(store):
    r = execute("get_review_counts", {}, store)
    assert r["needs_review"] == 1 and r["source"] == "review_counts"


def test_unknown_tool_is_graceful(store):
    r = execute("drop_table", {}, store)
    assert r["error"] == "unknown_tool"
