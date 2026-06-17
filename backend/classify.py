"""Classification (§7): invoice / credit_note / non_invoice.

A deterministic pre-filter rejects obvious junk (logos, signatures, calendar
invites) WITHOUT spending a Groq call (R9). Surviving documents go to the LLM —
text path uses the small classify model, image-only uses the vision model.
Unknown answers fail safe to non_invoice so junk is never stored as an expense.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from backend.config import get_settings
from backend.jsonutil import parse_json_object
from backend.llm import LLM, LLMImage, get_llm
from backend.schema import DocType

_JUNK_NAME = re.compile(r"(logo|signature|header|footer|banner|icon|avatar|stamp)", re.I)
_TINY_IMAGE_MAX_DIM = 300  # below this, an image is almost certainly a logo/sig

# Body-only email triage (R9): drop obvious promo/newsletter mail BEFORE the LLM.
# Conservative — a body carrying ANY invoice signal is never dropped, so a
# genuine body-only invoice (scenario 7) still goes through. Markers are kept
# STRONG (promo-only) on purpose: weak onboarding words like "get started" /
# "sign up" appear in legitimate transactional mail, so they are NOT listed —
# the language-agnostic RFC bulk-header signal (List-Unsubscribe etc., passed in
# as `bulk`) does the heavy lifting for those.
_PROMO_MARKERS = re.compile(
    r"(\bunsubscribe\b|view (this email|it) in (your )?browser|"
    r"manage (your )?(email )?preferences|email preferences|you('|’)?re receiving this|"
    r"\bfree trial\b|trial (has )?started|\bnewsletter\b|\d ?% off|"
    r"\bshop now\b|\blimited time\b|\bfollow us\b)",
    re.I,
)
_INVOICE_SIGNALS = re.compile(
    r"\b(invoice|tax invoice|amount due|total due|balance due|amount payable|"
    r"bill to|billed to|invoice (number|no|#)|remittance|subtotal|payment due|due date|"
    r"receipt|order total|vat( |-)?(no|number|reg))\b",
    re.I,
)


def is_probably_promo_body(subject: Optional[str], body: Optional[str],
                           *, bulk: bool = False) -> bool:
    """True when a body-only email is clearly promotional / non-invoice and not
    worth an LLM call. Only the email BODY path uses this — attachment-bearing
    mail always goes through (real invoices arrive as PDFs).

    `bulk` is the RFC bulk-mail signal from headers (List-Unsubscribe, Precedence:
    bulk, …): language-agnostic and far more robust than keyword matching."""
    blob = f"{subject or ''}\n{body or ''}"
    if _INVOICE_SIGNALS.search(blob):
        return False                       # any invoice cue -> keep, never drop
    return bulk or bool(_PROMO_MARKERS.search(blob))

_SYSTEM = (
    "You are an accounts-payable triage classifier. Decide whether a document is "
    'an "invoice", a "credit_note" (refund/credit memo, often negative), or a '
    '"non_invoice" (logo, signature, terms, marketing, calendar, anything that is '
    "not a billable document). Return ONLY a JSON object: "
    '{"doc_type": "invoice"|"credit_note"|"non_invoice", "confidence": 0..1}.'
)


@dataclass
class ClassifyResult:
    doc_type: DocType
    confidence: float

    @property
    def is_invoice(self) -> bool:
        # invoices and credit notes are both stored (credit notes reduce expense);
        # only non_invoice is skipped.
        return self.doc_type is not DocType.non_invoice


def is_probably_junk(filename: Optional[str], mime: Optional[str],
                     width: Optional[int] = None, height: Optional[int] = None) -> bool:
    """Cheap deterministic gate before any Groq call (R9)."""
    if mime:
        m = mime.lower()
        if m.startswith("text/calendar") or "vcard" in m or m == "text/x-vcard":
            return True
    if filename and _JUNK_NAME.search(filename):
        return True
    if width and height and max(width, height) < _TINY_IMAGE_MAX_DIM:
        return True
    return False


def classify_document(text: Optional[str] = None,
                      images: Optional[Sequence[LLMImage]] = None,
                      llm: Optional[LLM] = None) -> ClassifyResult:
    llm = llm or get_llm()
    settings = get_settings()
    model = settings.model_extract_vision if images else settings.model_classify
    user = text.strip() if text else "Classify the attached document image."
    raw = llm.complete(model, _SYSTEM, user, images=images, temperature=0.0, json_mode=True)
    data = parse_json_object(raw)
    try:
        doc_type = DocType(data.get("doc_type"))
    except ValueError:
        doc_type = DocType.non_invoice  # fail safe
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return ClassifyResult(doc_type=doc_type, confidence=max(0.0, min(1.0, confidence)))
