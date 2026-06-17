"""Validation + confidence + status (§7, R12). All deterministic. Totals must
reconcile within tolerance; multi-tax lines sum to tax_total; anything off (or
ambiguous date / handwritten / missing total) routes to needs_review."""
from decimal import Decimal

from backend.schema import RawExtraction
from backend.validate import assess, compute_confidence, decide_status, reconcile


def _ext(**over):
    base = {
        "doc_type": "invoice", "vendor_name": "Acme", "invoice_number": "INV-1",
        "currency": "USD", "subtotal": "100.00", "discount": "0", "shipping": "0",
        "tax_total": "20.00", "total": "120.00",
        "tax_lines": [{"label": "VAT", "rate": "20", "amount": "20.00"}],
        "line_items": [{"description": "Hosting", "amount": "100.00"}],
        "_confidence": {"total": 0.95},
    }
    base.update(over)
    return RawExtraction.model_validate(base)


def test_clean_invoice_reconciles():
    v = reconcile(_ext())
    assert v.totals_ok and v.tax_lines_ok and v.line_items_ok
    assert v.all_ok


def test_totals_within_tolerance_ok():
    v = reconcile(_ext(total="120.01"))   # 0.01 drift, within default tol
    assert v.totals_ok


def test_totals_mismatch_detected():
    v = reconcile(_ext(total="999.00"))
    assert v.totals_ok is False
    assert not v.all_ok


def test_tax_lines_sum_mismatch_detected():
    v = reconcile(_ext(tax_lines=[{"label": "VAT", "rate": "5", "amount": "5.00"}]))
    assert v.tax_lines_ok is False


def test_multi_tax_lines_sum_to_total():
    e = _ext(tax_total="18.00", total="118.00",
             tax_lines=[{"label": "CGST", "rate": "9", "amount": "9.00"},
                        {"label": "SGST", "rate": "9", "amount": "9.00"}])
    v = reconcile(e)
    assert v.tax_lines_ok and v.totals_ok


def test_fees_as_line_items_reconcile():
    # Airbnb-style: subtotal = nights only; the service fee is a separate line
    # item; total = nights + fee + tax. Must reconcile, NOT false-flag.
    e = _ext(subtotal="93988.00", tax_total="16917.84", total="124174.78",
             tax_lines=[{"label": "Taxes", "amount": "16917.84"}],
             line_items=[{"description": "4 nights", "amount": "93988.00"},
                         {"description": "Service fee", "amount": "13268.94"}])
    v = reconcile(e)
    assert v.totals_ok and v.line_items_ok and v.all_ok


def test_explicit_fees_field_reconcile():
    e = _ext(subtotal="100.00", fees="10.00", tax_total="20.00", total="130.00",
             line_items=[{"description": "x", "amount": "100.00"}])
    v = reconcile(e)
    assert v.totals_ok and v.all_ok


def test_status_clean_for_good_invoice():
    e = _ext()
    v = reconcile(e)
    conf, _ = compute_confidence(e, v)
    assert decide_status(conf, v) == "clean"
    assert conf > Decimal("0.75")


def test_status_needs_review_on_totals_mismatch():
    e = _ext(total="999.00")
    v = reconcile(e)
    conf, _ = compute_confidence(e, v)
    assert decide_status(conf, v) == "needs_review"


def test_ambiguous_date_forces_review():
    e = _ext()
    v = reconcile(e)
    conf, _ = compute_confidence(e, v, ambiguous_date=True)
    assert decide_status(conf, v, ambiguous_date=True) == "needs_review"


def test_handwritten_forces_review():
    e = _ext()
    v = reconcile(e)
    assert decide_status(Decimal("0.9"), v, is_handwritten=True) == "needs_review"


def test_missing_total_low_confidence_and_review():
    e = _ext(total=None)
    v = reconcile(e)
    conf, _ = compute_confidence(e, v)
    status = decide_status(conf, v)
    assert status == "needs_review"


def test_assess_bundles_everything():
    e = _ext()
    result = assess(e)
    assert result.status == "clean"
    assert result.confidence > Decimal("0.75")
    assert result.validation.all_ok
