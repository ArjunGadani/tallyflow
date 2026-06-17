"""Digest (§10). Aggregation + rendering are pure and tested; sending is live IO.
Digest must be consistent with stored data (net of credits, needs_review, etc.)."""
from decimal import Decimal

from backend.digest import build_digest_data, render_email_html, render_slack_blocks
from backend.store import LocalStore


def _seed() -> LocalStore:
    store = LocalStore(":memory:")
    vid = store.upsert_vendor("Acme", default_category=None)
    store.save_invoice({"vendor_id": vid, "doc_type": "invoice", "status": "clean",
                        "total": Decimal("100"), "base_total": Decimal("100"),
                        "base_currency": "GBP", "category": "Cloud", "is_invoice": True,
                        "file_hash": "h1"})
    store.save_invoice({"vendor_id": vid, "doc_type": "credit_note", "status": "credited",
                        "total": Decimal("-20"), "base_total": Decimal("-20"),
                        "base_currency": "GBP", "is_invoice": True, "file_hash": "h2"})
    store.save_invoice({"doc_type": "invoice", "status": "needs_review",
                        "total": Decimal("200"), "base_total": Decimal("200"),
                        "is_invoice": True, "file_hash": "h3"})
    store.add_dead_letter("bad.pdf", "h4", "boom", 4, "/tmp/x")
    return store


def test_build_digest_data_matches_stored():
    data = build_digest_data(_seed(), run_counts={"processed": 2, "skipped": 0, "failed": 1})
    assert data["total_spend"] == Decimal("80")          # 100 - 20
    assert data["credits_total"] == Decimal("20")
    assert data["needs_review_count"] == 1
    assert data["pending_review_excluded"] == Decimal("200")
    assert data["dead_letter_count"] == 1
    assert data["run"]["processed"] == 2
    assert ("Cloud", Decimal("100")) in data["top_categories"]


def test_render_email_html_contains_figures():
    html = render_email_html(build_digest_data(_seed()))
    assert "<html" in html.lower()
    assert "80.00" in html          # net spend
    assert "Needs review" in html or "needs review" in html.lower()


def test_render_slack_blocks_structure():
    blocks = render_slack_blocks(build_digest_data(_seed()))
    assert isinstance(blocks, list) and blocks
    flat = str(blocks)
    assert "80.00" in flat
