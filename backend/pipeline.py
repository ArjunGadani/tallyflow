"""Pipeline orchestration (§3). Ties the deterministic modules and the LLM
boundary into one flow, emitting an event at every step so the dashboard can
render the live processing timeline (§9).

Order: hash -> exact-dup gate -> classify -> type detect -> extract ->
normalize -> validate/confidence/status -> vendor + category -> resolve ->
currency convert -> atomic store (+ original retained) -> digest queued.

Hard failures (transient LLM errors, unrecoverable extraction) propagate; the
retry/dead-letter wrapper (Phase 6) and the API layer turn them into graceful
outcomes — this module never leaks a stack trace to a user.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from PIL import Image

from backend.classify import classify_document, is_probably_junk
from backend.config import get_settings
from backend.extract import extract_from_images, extract_from_text
from backend.fx import FXError, convert_to_base
from backend.llm import LLM, LLMImage, get_llm
from backend.normalize import normalize_currency, normalize_date, normalize_vendor
from backend.preprocess import (detect_pdf_page_types, extract_pdf_text,
                                pdf_page_count, pdf_to_images, preprocess_image)
from backend.resolve import ExistingInvoice, IncomingInvoice, resolve
from backend.schema import DocType
from backend.store import Store, get_store

# Currencies whose locale convention is month-first (resolves DD/MM ambiguity).
_MONTH_FIRST_CURRENCIES = {"USD", "CAD"}


@dataclass
class PipelineResult:
    invoice_id: Optional[str]
    branch: str
    status: str
    doc_type: str
    is_invoice: bool
    events: list = field(default_factory=list)
    message: str = ""


def _kind(mime: Optional[str], filename: Optional[str]) -> str:
    m = (mime or "").lower()
    f = (filename or "").lower()
    if "pdf" in m or f.endswith(".pdf"):
        return "pdf"
    if m.startswith("image/") or f.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")):
        return "image"
    return "text"


def _day_first_hint(currency: Optional[str]) -> Optional[bool]:
    if not currency:
        return None
    return False if currency in _MONTH_FIRST_CURRENCIES else True


def split_documents(file_bytes: bytes, mime: Optional[str],
                    filename: Optional[str]) -> list[tuple[bytes, str, str]]:
    """Split a multi-invoice PDF into separate documents (scenario 5); otherwise
    return the single document unchanged. Corrupt/unreadable input is returned
    as-is so process_document/run_safely can dead-letter it gracefully."""
    from backend.preprocess import split_pdf_by_invoice

    name = filename or "document"
    if _kind(mime, filename) != "pdf":
        return [(file_bytes, name, mime or "application/octet-stream")]
    try:
        subs = split_pdf_by_invoice(file_bytes)
    except Exception:
        return [(file_bytes, name, mime or "application/pdf")]
    if len(subs) <= 1:
        return [(file_bytes, name, mime or "application/pdf")]
    base = name.rsplit(".", 1)[0]
    return [(b, f"{base}_part{i + 1}.pdf", "application/pdf") for i, b in enumerate(subs)]


def process_document(file_bytes: bytes, filename: Optional[str], mime: Optional[str],
                     source: str = "upload", source_ref: Optional[str] = None, *,
                     llm: Optional[LLM] = None, store: Optional[Store] = None,
                     fx_source=None, metadata: Optional[dict] = None) -> PipelineResult:
    llm = llm or get_llm()
    store = store or get_store()
    settings = get_settings()
    events: list = []

    def ev(type_: str, **detail):
        # stamp emit-time so the timeline reflects real per-step durations
        events.append({"type": type_, "detail": detail,
                       "ts": datetime.now(timezone.utc).isoformat()})

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    # metadata (e.g. email arrival date/sender) is surfaced on the first event
    ev("received", filename=filename, mime=mime, source=source,
       file_hash=file_hash[:12], **(metadata or {}))

    # 1. exact-duplicate gate (idempotency) -------------------------------
    existing_id = store.exists_by_hash(file_hash)
    if existing_id:
        store.append_event(existing_id, "exact_duplicate_reprocessed",
                           {"file_hash": file_hash, "source_ref": source_ref})
        existing = store.get_invoice(existing_id)
        return PipelineResult(existing_id, "exact_duplicate", existing["status"],
                              existing["doc_type"], existing["is_invoice"],
                              events, "exact duplicate — not re-counted")

    # 2. type detect + build extraction inputs ----------------------------
    kind = _kind(mime, filename)
    text: Optional[str] = None
    images: Optional[list[LLMImage]] = None
    path: str
    pages = 1

    if kind == "pdf":
        pages = pdf_page_count(file_bytes)
        page_types = detect_pdf_page_types(file_bytes)
        if all(t == "digital" for t in page_types):
            text = extract_pdf_text(file_bytes)
            path = "text"
        else:
            images = [LLMImage(preprocess_image(b), "image/jpeg") for b in pdf_to_images(file_bytes)]
            path = "vision"
    elif kind == "image":
        w = h = None
        try:
            w, h = Image.open(io.BytesIO(file_bytes)).size
        except Exception:
            pass
        if is_probably_junk(filename, mime, w, h):
            ev("classified", doc_type="non_invoice", reason="junk pre-filter")
            return _store_non_invoice(store, file_hash, source, source_ref, filename,
                                      mime, file_bytes, pages, events, confidence=1.0)
        images = [LLMImage(preprocess_image(file_bytes), "image/jpeg")]
        path = "vision"
    else:
        text = file_bytes.decode("utf-8", errors="ignore")
        path = "text"
    ev("type_detected", path=path, pages=pages)

    # 3. classify ----------------------------------------------------------
    cls = classify_document(text=text, images=images, llm=llm)
    ev("classified", doc_type=cls.doc_type.value, confidence=cls.confidence)
    if cls.doc_type is DocType.non_invoice:
        return _store_non_invoice(store, file_hash, source, source_ref, filename,
                                  mime, file_bytes, pages, events, confidence=cls.confidence)

    # 4. extract -----------------------------------------------------------
    ext = (extract_from_text(text, llm=llm) if path == "text"
           else extract_from_images(images, llm=llm))
    ev("extracted", path=path, doc_type=ext.doc_type.value)

    # 5. normalize ---------------------------------------------------------
    currency = normalize_currency(ext.currency)
    day_first = _day_first_hint(currency)
    inv_date, ambiguous = normalize_date(ext.invoice_date, day_first_hint=day_first)
    due_date, _ = normalize_date(ext.due_date, day_first_hint=day_first)
    vendors = store.list_vendors()
    vm = normalize_vendor(ext.vendor_name, vendors)
    if vm.vendor_id:
        vendor_id = vm.vendor_id
    else:
        aliases = [ext.vendor_name] if ext.vendor_name and ext.vendor_name != vm.canonical_name else []
        vendor_id = store.upsert_vendor(vm.canonical_name, aliases=aliases)
    ev("normalized", vendor=vm.canonical_name, currency=currency, date_ambiguous=ambiguous)

    # 6. validate / confidence / status -----------------------------------
    from backend.validate import assess
    assessment = assess(ext, ambiguous_date=ambiguous)
    ev("validated", totals_ok=assessment.validation.totals_ok,
       tax_ok=assessment.validation.tax_lines_ok,
       line_ok=assessment.validation.line_items_ok,
       issues=assessment.validation.issues)
    ev("confidence_scored", overall=float(assessment.confidence))

    # 7. category (vendor-master rule overrides the LLM guess — R14) -------
    vendor_default = next((v["default_category"] for v in vendors if v["id"] == vendor_id), None)
    category = vendor_default or ext.category
    ev("vendor_matched", vendor_id=vendor_id, is_new=vm.is_new)
    ev("categorized", category=category)

    # 8. resolve (dedup / revision / credit) -------------------------------
    incoming = IncomingInvoice(file_hash, ext.doc_type, vendor_id, ext.invoice_number,
                               inv_date, ext.total, ext.referenced_invoice_number)
    candidates = [ExistingInvoice(
        id=c["id"], doc_type=DocType(c["doc_type"]), vendor_id=c["vendor_id"],
        invoice_number=c["invoice_number"], invoice_date=c["invoice_date"],
        total=c["total"], version=c["version"], status=c["status"],
        file_hash=c["file_hash"], referenced_invoice_number=c["referenced_invoice_number"],
    ) for c in store.candidates_for_vendor(vendor_id)]
    outcome = resolve(incoming, None, candidates)
    ev("resolved", branch=outcome.branch, **outcome.detail)

    if outcome.branch in ("exact_duplicate", "logical_duplicate"):
        if outcome.link_to_id:
            store.append_event(outcome.link_to_id, "duplicate_linked",
                               {"branch": outcome.branch, "file_hash": file_hash,
                                "source_ref": source_ref})
            linked = store.get_invoice(outcome.link_to_id)
            status, doc_type, is_inv = linked["status"], linked["doc_type"], linked["is_invoice"]
        else:
            status, doc_type, is_inv = "stored", ext.doc_type.value, True
        return PipelineResult(outcome.link_to_id, outcome.branch, status, doc_type,
                              is_inv, events, "duplicate — not re-counted")

    # 9. status resolution + currency conversion ---------------------------
    status = outcome.status_hint or assessment.status
    # Surface anything flagged by resolution (e.g. an orphan credit, R4) for human
    # linking — except a genuinely superseded older version, whose terminal state
    # is correct and whose reason is only informational (R3). A credit kept here as
    # needs_review still subtracts in the summary (which keys off doc_type).
    if outcome.needs_review_reason and status != "superseded":
        status = "needs_review"

    fx_date = inv_date or datetime.now(timezone.utc).date()
    base_total = fx_rate = fx_dt = None
    try:
        if ext.total is not None:
            base_total, fx_rate, fx_dt = convert_to_base(ext.total, currency, fx_date, source=fx_source)
    except FXError as exc:
        ev("currency_conversion_failed", error=str(exc))
        status = "needs_review"
    ev("currency_converted", base_currency=settings.base_currency,
       base_total=str(base_total) if base_total is not None else None,
       fx_rate=str(fx_rate) if fx_rate is not None else None)

    # 10. atomic store ------------------------------------------------------
    invoice_row = {
        "vendor_id": vendor_id, "invoice_number": ext.invoice_number,
        "invoice_date": inv_date, "due_date": due_date, "doc_type": ext.doc_type.value,
        "currency": currency, "subtotal": ext.subtotal, "tax_total": ext.tax_total,
        "discount": ext.discount, "shipping": ext.shipping, "total": ext.total,
        "base_currency": settings.base_currency, "base_total": base_total,
        "fx_rate": fx_rate, "fx_date": fx_dt, "category": category, "status": status,
        "version": outcome.version, "supersedes_id": outcome.supersedes_id,
        "credit_of_id": outcome.credit_of_id, "file_hash": file_hash, "source": source,
        "source_ref": source_ref, "confidence_overall": assessment.confidence,
        "is_invoice": True,
    }
    line_items = [{"description": li.description, "quantity": li.quantity,
                   "unit_price": li.unit_price, "amount": li.amount} for li in ext.line_items]
    tax_lines = [{"label": t.label, "rate": t.rate, "amount": t.amount} for t in ext.tax_lines]
    field_conf = [{"field": k, "confidence": v} for k, v in assessment.per_field.items()]
    events.append({"type": "stored", "detail": {"branch": outcome.branch, "status": status,
                                                 "version": outcome.version},
                   "ts": datetime.now(timezone.utc).isoformat()})

    invoice_id = store.save_invoice(invoice_row, line_items, tax_lines, field_conf, events,
                                    mark_superseded=outcome.mark_superseded_id)
    store.save_original(invoice_id, file_bytes, mime or "application/octet-stream",
                        filename or "original", pages)
    store.append_event(invoice_id, "digest_queued", {})

    return PipelineResult(invoice_id, outcome.branch, status, ext.doc_type.value, True,
                          store.get_invoice(invoice_id)["events"],
                          outcome.needs_review_reason or "")


def _store_non_invoice(store, file_hash, source, source_ref, filename, mime, file_bytes,
                       pages, events, confidence) -> PipelineResult:
    """Non-invoice attachments are retained (audit) but never counted as expense."""
    events.append({"type": "stored", "detail": {"branch": "non_invoice"},
                   "ts": datetime.now(timezone.utc).isoformat()})
    row = {"doc_type": "non_invoice", "status": "stored", "is_invoice": False,
           "file_hash": file_hash, "source": source, "source_ref": source_ref,
           "confidence_overall": confidence}
    invoice_id = store.save_invoice(row, events=events)
    store.save_original(invoice_id, file_bytes, mime or "application/octet-stream",
                        filename or "original", pages)
    return PipelineResult(invoice_id, "non_invoice", "stored", "non_invoice", False,
                          events, "classified non-invoice — skipped")
