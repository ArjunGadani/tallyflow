"""The local SQLite store is the dev stand-in for Supabase. It must honour the
two guarantees the whole system leans on (§0): atomic save (R5) and
exact-duplicate rejection by file_hash (idempotency). Money round-trips as
Decimal, never float."""
from datetime import date
from decimal import Decimal

import pytest

from backend.store import LocalStore


@pytest.fixture
def store():
    return LocalStore(":memory:")


def _invoice(**over):
    base = dict(
        invoice_number="INV-1042",
        doc_type="invoice",
        currency="USD",
        subtotal=Decimal("100.00"),
        tax_total=Decimal("20.00"),
        total=Decimal("120.00"),
        invoice_date=date(2026, 5, 1),
        status="clean",
        file_hash="hash-A",
    )
    base.update(over)
    return base


def test_save_and_get_roundtrip_preserves_decimal(store):
    iid = store.save_invoice(
        _invoice(),
        line_items=[dict(description="Hosting", quantity=Decimal("1"),
                         unit_price=Decimal("100.00"), amount=Decimal("100.00"))],
        tax_lines=[dict(label="VAT", rate=Decimal("20"), amount=Decimal("20.00"))],
        events=[dict(type="stored", detail={"branch": "new"})],
    )
    got = store.get_invoice(iid)
    assert got["total"] == Decimal("120.00")
    assert isinstance(got["total"], Decimal)
    assert got["invoice_date"] == date(2026, 5, 1)
    assert len(got["line_items"]) == 1
    assert got["tax_lines"][0]["amount"] == Decimal("20.00")
    assert got["events"][-1]["type"] == "stored"


def test_exists_by_hash(store):
    assert store.exists_by_hash("hash-A") is None
    iid = store.save_invoice(_invoice())
    assert store.exists_by_hash("hash-A") == iid


def test_duplicate_hash_rejected_atomically(store):
    store.save_invoice(_invoice(),
                       line_items=[dict(description="x", amount=Decimal("1"))])
    # Second save with the same file_hash must fail AND leave no orphan rows.
    with pytest.raises(Exception):
        store.save_invoice(_invoice(invoice_number="INV-DUP"),
                           line_items=[dict(description="y", amount=Decimal("2"))])
    assert store.count_invoices() == 1
    assert store.count_line_items() == 1  # only the first invoice's item


def test_append_event_is_ordered(store):
    iid = store.save_invoice(_invoice())
    store.append_event(iid, "classified", {"doc_type": "invoice"})
    store.append_event(iid, "extracted", {"path": "text"})
    types = [e["type"] for e in store.get_invoice(iid)["events"]]
    assert types == ["classified", "extracted"]


def test_review_counts(store):
    store.save_invoice(_invoice(status="needs_review", file_hash="h-nr"))
    store.add_dead_letter("x.pdf", "h", "boom", 4, "/tmp/x")
    c = store.review_counts()
    assert c["needs_review"] == 1 and c["dead_letter"] == 1 and c["total"] == 2


def test_email_processed_tracking(store):
    assert store.is_email_processed("<m1@x>") is False
    store.mark_email_processed("<m1@x>")
    assert store.is_email_processed("<m1@x>") is True
    store.mark_email_processed("<m1@x>")            # idempotent, no error


def test_activity_feed_is_lean_and_derived(store):
    iid = store.save_invoice(
        _invoice(),
        events=[
            {"type": "received", "detail": {"email_date": "2026-05-01T10:00:00+00:00"},
             "ts": "2026-05-01T10:00:00+00:00"},
            {"type": "resolved", "detail": {"branch": "new"}, "ts": "2026-05-01T10:00:05+00:00"},
            {"type": "stored", "detail": {}, "ts": "2026-05-01T10:00:06+00:00"},
        ],
    )
    store.add_dead_letter("bad@x.com", "h", "boom", 4, "/tmp/x")
    feed = store.activity_feed()
    assert len(feed) == 2
    inv_row = next(r for r in feed if r["invoice_id"] == iid)
    assert inv_row["branch"] == "new"
    assert inv_row["last_step"] == "stored"
    assert inv_row["arrival"] == "2026-05-01T10:00:00+00:00"
    assert inv_row["duration_ms"] == 6000          # received -> stored
    assert "line_items" not in inv_row             # lean: no child rows fetched
    dl_row = next(r for r in feed if r["invoice_id"] is None)
    assert dl_row["branch"] == "dead_letter" and dl_row["source"] == "email"


def test_activity_feed_orders_newest_first_and_survives_null_branch(store):
    older = store.save_invoice(
        _invoice(file_hash="h-old", invoice_number="OLD"),
        events=[{"type": "received", "detail": {}, "ts": "2026-05-01T10:00:00+00:00"},
                {"type": "resolved", "detail": None, "ts": "2026-05-01T10:00:01+00:00"}],
    )
    newer = store.save_invoice(
        _invoice(file_hash="h-new", invoice_number="NEW"),
        events=[{"type": "received", "detail": {}, "ts": "2026-05-09T10:00:00+00:00"},
                {"type": "stored", "detail": {}, "ts": "2026-05-09T10:00:02+00:00"}],
    )
    feed = store.activity_feed()
    ids = [r["invoice_id"] for r in feed if r["invoice_id"]]
    assert ids.index(newer) < ids.index(older)        # newest first
    # resolved event with detail=None must not crash; branch falls back to doc_type
    assert next(r for r in feed if r["invoice_id"] == older)["branch"] == "new"


def test_list_invoices_is_lean(store):
    store.save_invoice(_invoice(),
                       line_items=[dict(description="x", amount=Decimal("1"))])
    rows = store.list_invoices()
    assert len(rows) == 1
    assert rows[0]["total"] == Decimal("120.00")     # scalar fields hydrated
    assert "vendor_name" in rows[0]
    assert "line_items" not in rows[0]               # lean: no children fetched


def test_delete_invoice_cascades_and_clears_refs(store):
    old = store.save_invoice(
        _invoice(file_hash="h-old", invoice_number="INV-1"),
        line_items=[dict(description="x", amount=Decimal("1"))],
        tax_lines=[dict(label="VAT", amount=Decimal("0.20"))],
        events=[dict(type="stored", detail={})])
    new = store.save_invoice(_invoice(file_hash="h-new", invoice_number="INV-1",
                                      version=2, supersedes_id=old))
    assert store.delete_invoice(old) is True
    assert store.get_invoice(old) is None
    assert store.count_line_items() == 0             # children cascaded
    assert store.get_invoice(new)["supersedes_id"] is None   # dangling ref cleared
    assert store.delete_invoice("does-not-exist") is False


def test_activity_duration_ignores_late_reprocess(store):
    iid = store.save_invoice(
        _invoice(),
        events=[
            {"type": "received", "detail": {}, "ts": "2026-05-01T10:00:00+00:00"},
            {"type": "stored", "detail": {}, "ts": "2026-05-01T10:00:03+00:00"},
            # a re-uploaded exact duplicate appends this ~99 min later
            {"type": "exact_duplicate_reprocessed", "detail": {}, "ts": "2026-05-01T11:39:00+00:00"},
        ],
    )
    row = next(r for r in store.activity_feed() if r["invoice_id"] == iid)
    assert row["duration_ms"] == 3000     # received -> stored, NOT received -> reprocess


def test_list_invoices_date_filter(store):
    store.save_invoice(_invoice(file_hash="a", invoice_number="A", invoice_date=date(2026, 1, 15)))
    store.save_invoice(_invoice(file_hash="b", invoice_number="B", invoice_date=date(2026, 3, 20)))
    store.save_invoice(_invoice(file_hash="c", invoice_number="C", invoice_date=date(2026, 6, 10)))
    feb_apr = sorted(r["invoice_number"] for r in
                     store.list_invoices(date_from="2026-02-01", date_to="2026-04-30"))
    assert feb_apr == ["B"]                                   # only the in-range one
    assert len(store.list_invoices(date_from="2026-03-01")) == 2   # B, C
    assert len(store.list_invoices(date_to="2026-02-01")) == 1     # A
    assert len(store.list_invoices()) == 3                          # unfiltered


def test_app_settings_roundtrip(store):
    assert store.get_setting("digest_enabled") is None
    assert store.get_setting("digest_enabled", "true") == "true"      # default
    store.set_setting("digest_enabled", "false")
    assert store.get_setting("digest_enabled", "true") == "false"
    store.set_setting("digest_enabled", "true")                       # upsert
    assert store.get_setting("digest_enabled") == "true"


def test_activity_feed_respects_limit(store):
    for i in range(5):
        store.save_invoice(_invoice(file_hash=f"h{i}", invoice_number=f"INV-{i}"))
    assert len(store.activity_feed(limit=2)) == 2


def test_event_timestamp_preserved(store):
    iid = store.save_invoice(
        _invoice(),
        events=[{"type": "received", "detail": {}, "ts": "2026-01-02T03:04:05+00:00"}],
    )
    assert store.get_invoice(iid)["events"][0]["ts"] == "2026-01-02T03:04:05+00:00"


def test_save_marks_prior_superseded(store):
    old = store.save_invoice(_invoice(file_hash="hash-A"))
    new = store.save_invoice(
        _invoice(file_hash="hash-B", invoice_number="INV-1042", version=2,
                 supersedes_id=old),
        mark_superseded=old,
    )
    assert store.get_invoice(old)["status"] == "superseded"
    assert store.get_invoice(new)["version"] == 2
