"""Dedup / revision / credit-note resolution (§6) — the heart of the system.

Pure deterministic decision. The pipeline fetches the exact-hash row and the
vendor's candidate invoices, then calls resolve(); the LLM is never involved.

Order (reordered per R1 so credit notes also dedup):
  1. exact duplicate (file_hash)            -> link, no expense impact
  2. logical duplicate (ANY doc_type)       -> link, no expense impact
  3. credit note                            -> link to referenced (or orphan, R4)
  4. invoice revision vs new                -> supersede latest, with date guard R3
  5. brand new

Revision-vs-duplicate uses a tolerance band (R2): totals within tolerance + same
date => duplicate (noisy re-read); a material difference => revision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from backend.config import get_settings
from backend.schema import DocType


@dataclass
class IncomingInvoice:
    file_hash: str
    doc_type: DocType
    vendor_id: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[date]
    total: Optional[Decimal]
    referenced_invoice_number: Optional[str] = None


@dataclass
class ExistingInvoice:
    id: str
    doc_type: DocType
    vendor_id: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[date]
    total: Optional[Decimal]
    version: int
    status: str
    file_hash: Optional[str] = None
    referenced_invoice_number: Optional[str] = None


@dataclass
class ResolutionOutcome:
    branch: str                              # exact_duplicate|logical_duplicate|revision|revision_late|credit_note|credit_orphan|new
    link_to_id: Optional[str] = None         # dup target / credit reference / superseded row
    supersedes_id: Optional[str] = None
    credit_of_id: Optional[str] = None
    mark_superseded_id: Optional[str] = None
    version: int = 1
    status_hint: Optional[str] = None        # forces row status (credited / superseded); else pipeline uses validation status
    needs_review_reason: Optional[str] = None
    detail: dict = field(default_factory=dict)


def _norm_num(n: Optional[str]) -> Optional[str]:
    if not n:
        return None
    return " ".join(n.strip().upper().split())


def _money_close(a: Optional[Decimal], b: Optional[Decimal],
                 tol_abs: Decimal, tol_pct: Decimal) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol_abs, tol_pct * max(abs(a), abs(b)))


def _logical_match(inc: IncomingInvoice, e: ExistingInvoice,
                   tol_abs: Decimal, tol_pct: Decimal) -> bool:
    if inc.invoice_number and e.invoice_number:
        return (inc.vendor_id == e.vendor_id
                and _norm_num(inc.invoice_number) == _norm_num(e.invoice_number))
    # No invoice number on the incoming doc -> fuzzy key (vendor, date, total) (§6.4).
    if inc.invoice_number is None:
        if inc.vendor_id != e.vendor_id:
            return False
        if inc.invoice_date and e.invoice_date and inc.invoice_date != e.invoice_date:
            return False
        return _money_close(inc.total, e.total, tol_abs, tol_pct)
    return False


def _is_identical(inc: IncomingInvoice, e: ExistingInvoice,
                  tol_abs: Decimal, tol_pct: Decimal) -> bool:
    return _money_close(inc.total, e.total, tol_abs, tol_pct) and inc.invoice_date == e.invoice_date


def _latest(invoices: list[ExistingInvoice]) -> ExistingInvoice:
    return max(invoices, key=lambda e: (e.version, e.invoice_date or date.min))


def _find_referenced(inc: IncomingInvoice, candidates: list[ExistingInvoice]) -> Optional[ExistingInvoice]:
    ref = _norm_num(inc.referenced_invoice_number)
    if not ref:
        return None
    hits = [e for e in candidates if _norm_num(e.invoice_number) == ref
            and e.doc_type is not DocType.credit_note]
    return hits[0] if hits else None


def resolve(inc: IncomingInvoice, existing_by_hash: Optional[ExistingInvoice],
            candidates: list[ExistingInvoice],
            tol_abs: Optional[Decimal] = None, tol_pct: Optional[Decimal] = None) -> ResolutionOutcome:
    s = get_settings()
    tol_abs = tol_abs if tol_abs is not None else s.revision_tolerance_abs
    tol_pct = tol_pct if tol_pct is not None else s.revision_tolerance_pct

    # 1. exact duplicate
    if existing_by_hash is not None:
        return ResolutionOutcome(branch="exact_duplicate", link_to_id=existing_by_hash.id,
                                 detail={"file_hash": inc.file_hash})

    matches = [e for e in candidates if _logical_match(inc, e, tol_abs, tol_pct)]
    active = [e for e in matches if e.status != "superseded"]

    # 2. logical duplicate (ALL doc types — R1; dedups credit notes too)
    for e in active:
        if e.doc_type is inc.doc_type and _is_identical(inc, e, tol_abs, tol_pct):
            return ResolutionOutcome(branch="logical_duplicate", link_to_id=e.id,
                                     detail={"matched": e.id})

    # 3. revision — a logical match that isn't identical. Applies to ANY doc_type,
    #    so a revised credit note supersedes the prior credit instead of stacking a
    #    second one (double-count guard).
    pool = active or matches
    if pool:
        target = _latest(pool)
        # R3 date guard: an older version arriving late must NOT supersede a newer one.
        if (inc.invoice_date and target.invoice_date and inc.invoice_date < target.invoice_date):
            return ResolutionOutcome(branch="revision_late", link_to_id=target.id,
                                     version=target.version, status_hint="superseded",
                                     needs_review_reason="older version arrived after a newer one",
                                     detail={"newer": target.id})
        # Preserve the credit linkage on a revised credit note.
        credit_of = None
        if inc.doc_type is DocType.credit_note:
            ref = _find_referenced(inc, candidates)
            credit_of = ref.id if ref else None
        return ResolutionOutcome(branch="revision", link_to_id=target.id,
                                 supersedes_id=target.id, mark_superseded_id=target.id,
                                 credit_of_id=credit_of, version=target.version + 1,
                                 detail={"supersedes": target.id})

    # 4. credit note with no prior version -> link to referenced invoice (or orphan, R4)
    if inc.doc_type is DocType.credit_note:
        ref = _find_referenced(inc, candidates)
        if ref is not None:
            return ResolutionOutcome(branch="credit_note", credit_of_id=ref.id, link_to_id=ref.id,
                                     status_hint="credited",
                                     detail={"credit_of": ref.id, "ref": inc.referenced_invoice_number})
        return ResolutionOutcome(branch="credit_orphan", status_hint="credited",
                                 needs_review_reason="referenced invoice not found",
                                 detail={"ref": inc.referenced_invoice_number})

    # 5. brand new
    return ResolutionOutcome(branch="new", version=1, detail={})
