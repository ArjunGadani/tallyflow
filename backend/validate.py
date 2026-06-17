"""Validation, confidence, and status — all deterministic (§7, R12).

Totals reconcile within tolerance; multi-tax lines sum to tax_total; line items
sum to subtotal. Confidence is driven mostly by these deterministic signals and
only lightly by the model's self-reported confidence (LLMs are poorly calibrated,
R12). Anything that fails reconciliation, has an ambiguous date, is handwritten,
or scores below threshold routes to needs_review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from backend.config import get_settings
from backend.schema import RawExtraction

_Z = Decimal(0)


@dataclass
class ValidationResult:
    totals_ok: bool = True
    tax_lines_ok: bool = True
    line_items_ok: bool = True
    issues: list[str] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return self.totals_ok and self.tax_lines_ok and self.line_items_ok


@dataclass
class AssessResult:
    validation: ValidationResult
    confidence: Decimal
    per_field: dict
    status: str


def _within(diff: Decimal, base: Optional[Decimal], tol_abs: Decimal, tol_pct: Decimal) -> bool:
    limit = max(tol_abs, tol_pct * abs(base or _Z))
    return abs(diff) <= limit


def reconcile(e: RawExtraction, tol_abs: Optional[Decimal] = None,
              tol_pct: Optional[Decimal] = None) -> ValidationResult:
    s = get_settings()
    tol_abs = tol_abs if tol_abs is not None else s.totals_tolerance_abs
    tol_pct = tol_pct if tol_pct is not None else s.totals_tolerance_pct
    r = ValidationResult()

    disc = e.discount or _Z
    tax = e.tax_total or _Z
    ship = e.shipping or _Z
    fees = e.fees or _Z
    li_sum = sum((li.amount or _Z for li in e.line_items), _Z) if e.line_items else None

    # Totals: the total must be explained by SOME consistent breakdown. Fees may
    # sit in the subtotal, in the `fees` field, or be booked as their own line
    # items — so we try each basis and pass if any reconciles (generic fee/
    # discount handling, not a single rigid formula).
    if e.total is not None:
        candidates: list[Decimal] = []
        if e.subtotal is not None:
            candidates.append(e.subtotal - disc + tax + ship + fees)
        if li_sum is not None:
            candidates.append(li_sum - disc + tax + ship)  # line items already include subtotal + fees
            candidates.append(li_sum + tax)                 # everything bundled into line items
        if candidates and not any(_within(c - e.total, e.total, tol_abs, tol_pct) for c in candidates):
            r.totals_ok = False
            r.issues.append(f"total {e.total} not explained by components {[str(c) for c in candidates]}")

    if e.tax_lines and e.tax_total is not None:
        summed = sum((t.amount or _Z for t in e.tax_lines), _Z)
        if not _within(summed - e.tax_total, e.tax_total, tol_abs, tol_pct):
            r.tax_lines_ok = False
            r.issues.append(f"tax lines sum {summed} != tax_total {e.tax_total}")

    # Line items are consistent if they match the subtotal OR (with tax) explain
    # the total — the latter covers fees booked as separate line items.
    if li_sum is not None and e.subtotal is not None:
        matches_subtotal = _within(li_sum - e.subtotal, e.subtotal, tol_abs, tol_pct)
        explains_total = e.total is not None and (
            _within((li_sum - disc + tax + ship) - e.total, e.total, tol_abs, tol_pct)
            or _within((li_sum + tax) - e.total, e.total, tol_abs, tol_pct))
        if not (matches_subtotal or explains_total):
            r.line_items_ok = False
            r.issues.append(f"line items sum {li_sum} != subtotal {e.subtotal}")

    return r


def compute_confidence(e: RawExtraction, validation: ValidationResult, *,
                       ambiguous_date: bool = False,
                       is_handwritten: bool = False) -> tuple[Decimal, dict]:
    """Deterministic-weighted confidence (R12). Model self-confidence contributes
    only 20%."""
    det = Decimal("1.0")
    if not validation.totals_ok:
        det -= Decimal("0.40")
    if not validation.tax_lines_ok:
        det -= Decimal("0.15")
    if not validation.line_items_ok:
        det -= Decimal("0.15")
    if ambiguous_date:
        det -= Decimal("0.20")
    if is_handwritten:
        det -= Decimal("0.30")
    if e.invoice_number is None:
        det -= Decimal("0.10")
    if e.total is None:
        det -= Decimal("0.40")
    if e.vendor_name is None:
        det -= Decimal("0.10")
    det = _clamp(det)

    model_vals = [Decimal(str(v)) for v in e.confidence.values()] if e.confidence else []
    model_avg = (sum(model_vals, _Z) / len(model_vals)) if model_vals else Decimal("0.7")

    overall = _clamp(Decimal("0.8") * det + Decimal("0.2") * model_avg)
    return overall, dict(e.confidence)


def decide_status(confidence: Decimal, validation: ValidationResult, *,
                  ambiguous_date: bool = False, is_handwritten: bool = False) -> str:
    if not validation.all_ok:
        return "needs_review"
    if ambiguous_date or is_handwritten:
        return "needs_review"
    if confidence < get_settings().confidence_review_threshold:
        return "needs_review"
    return "clean"


def assess(e: RawExtraction, *, ambiguous_date: bool = False,
           is_handwritten: bool = False) -> AssessResult:
    v = reconcile(e)
    conf, per_field = compute_confidence(e, v, ambiguous_date=ambiguous_date,
                                         is_handwritten=is_handwritten)
    status = decide_status(conf, v, ambiguous_date=ambiguous_date, is_handwritten=is_handwritten)
    return AssessResult(validation=v, confidence=conf, per_field=per_field, status=status)


def _clamp(x: Decimal) -> Decimal:
    return max(_Z, min(Decimal("1"), x))
