"""Reconciled expense summary (§27). Pure aggregation over already-fetched
invoice rows; the caller (store) excludes nothing — this function applies the
rules: skip superseded, subtract credit notes, exclude needs_review/failed from
the headline total but surface them separately (Q2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

_Z = Decimal(0)
_SPEND_STATUSES = {"clean", "stored"}
_PENDING_STATUSES = {"needs_review", "failed"}


@dataclass
class ExpenseSummary:
    base_currency: str
    total_spend: Decimal = _Z
    invoices_counted: int = 0
    credits_total: Decimal = _Z
    pending_review_excluded: Decimal = _Z
    needs_review_count: int = 0
    by_category: dict = field(default_factory=dict)
    by_vendor: dict = field(default_factory=dict)


def _dec(v) -> Decimal:
    if v is None:
        return _Z
    return v if isinstance(v, Decimal) else Decimal(str(v))


def reconcile_summary(rows: list[dict], base_currency: str) -> ExpenseSummary:
    s = ExpenseSummary(base_currency=base_currency)
    for r in rows:
        if r.get("status") == "superseded":
            continue
        if r.get("doc_type") == "non_invoice" or r.get("is_invoice") is False:
            continue  # classified junk is retained but never counted as expense
        bt = _dec(r.get("base_total"))

        if r.get("doc_type") == "credit_note":
            amt = abs(bt)
            s.credits_total += amt
            s.total_spend -= amt
            continue

        status = r.get("status")
        if status in _PENDING_STATUSES:
            s.pending_review_excluded += bt
            if status == "needs_review":
                s.needs_review_count += 1
            continue

        if status in _SPEND_STATUSES:
            s.total_spend += bt
            s.invoices_counted += 1
            cat = r.get("category") or "Uncategorized"
            ven = r.get("vendor") or "Unknown"
            s.by_category[cat] = s.by_category.get(cat, _Z) + bt
            s.by_vendor[ven] = s.by_vendor.get(ven, _Z) + bt

    return s
