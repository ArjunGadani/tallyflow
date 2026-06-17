"""Reconciled expense summary (§27): latest non-superseded - credits, deduped,
base currency. needs_review is EXCLUDED from the total but surfaced separately
(Q2) so spend is never silently understated."""
from decimal import Decimal

from backend.summary import reconcile_summary


def _row(**o):
    base = dict(status="clean", doc_type="invoice", base_total=Decimal("100"),
                category="Cloud", vendor="Acme")
    base.update(o)
    return base


def test_empty_is_zero():
    s = reconcile_summary([], "GBP")
    assert s.total_spend == Decimal("0")
    assert s.invoices_counted == 0


def test_sums_clean_invoices_net_of_credits():
    rows = [
        _row(base_total=Decimal("100"), category="Cloud", vendor="Acme"),
        _row(base_total=Decimal("50"), category="Office", vendor="Depot"),
        _row(doc_type="credit_note", status="credited", base_total=Decimal("-20")),
    ]
    s = reconcile_summary(rows, "GBP")
    assert s.total_spend == Decimal("130")     # 150 - 20
    assert s.credits_total == Decimal("20")
    assert s.invoices_counted == 2
    assert s.by_category["Cloud"] == Decimal("100")
    assert s.by_vendor["Depot"] == Decimal("50")


def test_needs_review_excluded_but_surfaced():
    rows = [_row(base_total=Decimal("100")),
            _row(status="needs_review", base_total=Decimal("200"))]
    s = reconcile_summary(rows, "GBP")
    assert s.total_spend == Decimal("100")
    assert s.pending_review_excluded == Decimal("200")
    assert s.needs_review_count == 1


def test_superseded_excluded():
    rows = [_row(base_total=Decimal("100")),
            _row(status="superseded", base_total=Decimal("999"))]
    s = reconcile_summary(rows, "GBP")
    assert s.total_spend == Decimal("100")


def test_non_invoice_excluded():
    rows = [_row(base_total=Decimal("100")),
            _row(doc_type="non_invoice", is_invoice=False, status="stored",
                 base_total=Decimal("0"))]
    s = reconcile_summary(rows, "GBP")
    assert s.total_spend == Decimal("100")
    assert s.invoices_counted == 1
