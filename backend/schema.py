"""Pydantic models for the system.

`RawExtraction` is the strict contract for what the LLM returns (§7). The LLM is
told to emit plain decimals, but models drift, so money fields run through a
deterministic cleaner (strip symbols/commas/whitespace, parens => negative,
blank => None). This cleaning is plain code, not the LLM — it just hardens the
parse boundary. Full normalization (dates->ISO, currency->ISO, vendor->canonical)
lives in normalize.py.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class DocType(str, Enum):
    invoice = "invoice"
    credit_note = "credit_note"
    non_invoice = "non_invoice"


_BLANKS = {"", "-", "--", "n/a", "na", "none", "null", "."}


def _clean_money(v: object) -> Optional[Decimal]:
    """Coerce an LLM-supplied money value to Decimal, or None if absent.

    Deterministic. Never raises on junk for an empty marker; raises only when a
    non-empty value is genuinely unparseable (so the repair-retry can catch it).
    """
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):  # guard: bool is an int subclass
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    s = str(v).strip()
    if s.lower() in _BLANKS:
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    # Keep only digits, decimal point, and leading minus (drops $, £, commas, spaces, ISO codes).
    s = re.sub(r"[^\d.\-]", "", s)
    if s in _BLANKS or s == "-":
        return None
    try:
        d = Decimal(s)
    except InvalidOperation as exc:  # genuinely malformed -> surface to repair-retry
        raise ValueError(f"unparseable money value: {v!r}") from exc
    return -d if negative else d


Money = Annotated[Optional[Decimal], BeforeValidator(_clean_money)]


class RawTaxLine(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: Optional[str] = None
    rate: Money = None
    amount: Money = None


class RawLineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: Optional[str] = None
    quantity: Money = None
    unit_price: Money = None
    amount: Money = None


class RawExtraction(BaseModel):
    """Exact shape of the extraction JSON the LLM must return (§7 schema)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    doc_type: DocType
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    invoice_number: Optional[str] = None
    referenced_invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None  # raw; normalized to ISO later
    due_date: Optional[str] = None
    currency: Optional[str] = None      # raw; normalized to ISO code later
    subtotal: Money = None
    discount: Money = None
    shipping: Money = None
    fees: Money = None  # generic extra charges (service/booking/processing) shown separately
    tax_lines: list[RawTaxLine] = Field(default_factory=list)
    tax_total: Money = None
    total: Money = None
    line_items: list[RawLineItem] = Field(default_factory=list)
    # Categorization folded into extraction to save a call (§0). Deterministic
    # vendor-master rules OVERRIDE this later (R14); this is the fallback guess.
    category: Optional[str] = None
    # LLM self-reported per-field confidence (0..1). Display only; deterministic
    # validation drives the real confidence (R12). Aliased from "_confidence".
    confidence: dict[str, float] = Field(default_factory=dict, alias="_confidence")
