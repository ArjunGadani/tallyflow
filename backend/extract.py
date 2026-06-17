"""Extraction core (§7).

The LLM only reads the document into the strict JSON schema. Everything around
it is deterministic: routing (text vs vision), JSON recovery, schema validation,
repair-retry on malformed output (R7), and cross-batch merge when a scanned doc
exceeds Groq's 5-image limit (R6). Categorization is folded into the same call
(§0) — a fallback the vendor-master rules later override (R14).
"""
from __future__ import annotations

from typing import Optional, Sequence

from pydantic import ValidationError

from backend.config import get_settings
from backend.jsonutil import parse_json_object
from backend.llm import LLM, LLMError, LLMImage, get_llm
from backend.preprocess import GROQ_MAX_IMAGES_PER_REQUEST, chunk_images
from backend.schema import RawExtraction

EXTRACTION_SYSTEM = (
    "You are an accounts-payable extraction engine. From the provided document, "
    "return ONLY a JSON object matching the schema. Rules:\n"
    '- First determine doc_type: "invoice", "credit_note", or "non_invoice".\n'
    "- Use null for any field not present. NEVER guess or fabricate.\n"
    "- Dates YYYY-MM-DD; if format is ambiguous, return best guess and set its "
    "confidence low. Numbers as plain decimals, no symbols. Currency as ISO code.\n"
    "- Capture every line item and every tax line separately.\n"
    "- Put any extra charges (service/booking/processing fee) in `fees` AND as a "
    "line item if listed.\n"
    "- For a credit note, capture the referenced invoice number if present.\n"
    "- Infer a short expense category from vendor + line items (e.g. "
    '"Cloud Hosting", "Office Supplies", "Travel").\n'
    '- Provide a 0..1 confidence for each top-level field in "_confidence".\n'
    "- Output nothing except the JSON object.\n"
    "Schema: { doc_type, vendor_name, vendor_address, invoice_number, "
    "referenced_invoice_number, invoice_date, due_date, currency, subtotal, "
    "discount, shipping, fees, tax_lines:[{label,rate,amount}], tax_total, total, "
    "line_items:[{description,quantity,unit_price,amount}], category, "
    "_confidence:{...} }"
)

_REPAIR_SUFFIX = (
    "\n\nYour previous response was not valid JSON for the schema. "
    "Return ONLY the JSON object, nothing else."
)

# Scalar fields merged by "first non-null across ordered batches" (R6).
_SCALAR_FIELDS = [
    "doc_type", "vendor_name", "vendor_address", "invoice_number",
    "referenced_invoice_number", "invoice_date", "due_date", "currency",
    "subtotal", "discount", "shipping", "tax_total", "total", "category",
]


class ExtractionError(Exception):
    """Extraction failed after repair attempts (caller may dead-letter)."""


def _call_and_parse(llm: LLM, model: str, user: str,
                    images: Optional[Sequence[LLMImage]], max_attempts: int) -> RawExtraction:
    """One extraction with up to `max_attempts` tries (initial + repairs)."""
    last_err: Optional[Exception] = None
    for attempt in range(max_attempts):
        prompt = user if attempt == 0 else user + _REPAIR_SUFFIX
        try:
            raw = llm.complete(model, EXTRACTION_SYSTEM, prompt, images=images,
                               temperature=0.0, json_mode=True)
            data = parse_json_object(raw)
            return RawExtraction.model_validate(data)
        except (ValueError, ValidationError) as exc:
            last_err = exc          # malformed/parse/schema -> repair
            continue
        except LLMError:
            raise                   # transient/permanent LLM errors bubble to retry layer
    raise ExtractionError(f"extraction failed after {max_attempts} attempts: {last_err}")


def extract_from_text(text: str, llm: Optional[LLM] = None, max_attempts: int = 2) -> RawExtraction:
    """Digital path: extracted PDF/body text -> text model."""
    llm = llm or get_llm()
    model = get_settings().model_extract_text
    return _call_and_parse(llm, model, text, images=None, max_attempts=max_attempts)


def extract_from_images(images: Sequence[LLMImage], llm: Optional[LLM] = None,
                        max_attempts: int = 2) -> RawExtraction:
    """Vision path: image(s) -> vision model. >5 images are chunked then merged."""
    llm = llm or get_llm()
    model = get_settings().model_extract_vision
    user = "Extract the invoice from the attached document image(s)."
    batches = chunk_images(list(images), GROQ_MAX_IMAGES_PER_REQUEST)
    parts = [_call_and_parse(llm, model, user, batch, max_attempts) for batch in batches]
    return merge_extractions(parts)


def merge_extractions(parts: Sequence[RawExtraction]) -> RawExtraction:
    """Combine batch extractions of ONE logical document (R6). Line/tax items are
    concatenated in order; scalars take the first non-null; confidences merge."""
    if not parts:
        raise ExtractionError("nothing to merge")
    if len(parts) == 1:
        return parts[0]

    merged: dict = {}
    for field in _SCALAR_FIELDS:
        for part in parts:
            val = getattr(part, field)
            if val is not None:
                merged[field] = val.value if hasattr(val, "value") else val
                break

    line_items: list = []
    tax_lines: list = []
    confidence: dict = {}
    for part in parts:
        line_items.extend(part.line_items)
        tax_lines.extend(part.tax_lines)
        confidence.update(part.confidence)

    merged["doc_type"] = merged.get("doc_type") or parts[0].doc_type
    out = RawExtraction.model_validate({"doc_type": merged["doc_type"]})
    for field, val in merged.items():
        setattr(out, field, val)
    out.line_items = line_items
    out.tax_lines = tax_lines
    out.confidence = confidence
    return out
