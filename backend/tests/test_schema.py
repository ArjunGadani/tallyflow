"""The LLM extraction contract (§7). Money is Decimal; missing is null, never
fabricated; doc_type is a closed enum; money strings are defensively cleaned
(deterministic, not LLM) so a stray symbol/comma doesn't poison the math."""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.schema import DocType, RawExtraction


FULL = {
    "doc_type": "invoice",
    "vendor_name": "Acme Web Services",
    "vendor_address": "1 Cloud Way",
    "invoice_number": "INV-1042",
    "referenced_invoice_number": None,
    "invoice_date": "2026-05-01",
    "due_date": "2026-05-31",
    "currency": "USD",
    "subtotal": "100.00",
    "discount": "0",
    "shipping": "0",
    "tax_lines": [{"label": "VAT", "rate": "20", "amount": "20.00"}],
    "tax_total": "20.00",
    "total": "120.00",
    "line_items": [
        {"description": "Hosting", "quantity": "1", "unit_price": "100.00", "amount": "100.00"}
    ],
    "_confidence": {"total": 0.98, "invoice_number": 0.95},
}


def test_parses_full_invoice_with_decimal_money():
    r = RawExtraction.model_validate(FULL)
    assert r.doc_type is DocType.invoice
    assert r.total == Decimal("120.00")
    assert isinstance(r.total, Decimal)
    assert r.tax_lines[0].amount == Decimal("20.00")
    assert r.line_items[0].description == "Hosting"
    assert r.confidence["total"] == pytest.approx(0.98)


def test_missing_fields_become_none_not_fabricated():
    r = RawExtraction.model_validate({"doc_type": "invoice"})
    assert r.invoice_number is None
    assert r.total is None
    assert r.tax_lines == []
    assert r.line_items == []
    assert r.confidence == {}


def test_doc_type_enum_rejects_unknown():
    with pytest.raises(ValidationError):
        RawExtraction.model_validate({"doc_type": "banana"})


def test_money_strips_symbols_commas_whitespace():
    r = RawExtraction.model_validate(
        {"doc_type": "invoice", "total": "$1,234.50", "subtotal": " 1 200.00 "}
    )
    assert r.total == Decimal("1234.50")
    assert r.subtotal == Decimal("1200.00")


def test_parenthesised_amount_is_negative():
    # Accounting convention on credit notes: (50.00) means -50.00.
    r = RawExtraction.model_validate({"doc_type": "credit_note", "total": "(50.00)"})
    assert r.total == Decimal("-50.00")


def test_empty_money_string_is_none():
    r = RawExtraction.model_validate({"doc_type": "invoice", "total": "", "discount": "-"})
    assert r.total is None
    assert r.discount is None
