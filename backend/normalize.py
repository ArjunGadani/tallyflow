"""Deterministic normalization (§0, §7). Dates -> ISO (ambiguity flagged),
currency -> ISO code, vendor -> canonical via fuzzy string match (NOT the LLM).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from dateutil import parser as duparser
from rapidfuzz import fuzz

from backend.config import get_settings

# --- dates -------------------------------------------------------------------
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC = re.compile(r"^\s*(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})\s*$")


def normalize_date(raw: Optional[str], *, day_first_hint: Optional[bool] = None) -> tuple[Optional[date], bool]:
    """Return (iso_date | None, ambiguous). ambiguous=True when we had to guess
    between DD/MM and MM/DD, or when parsing failed (flag for review, §19)."""
    if raw is None or not str(raw).strip():
        return (None, False)            # absent != ambiguous (don't force review)
    s = str(raw).strip()

    m = _ISO.match(s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))

    m = _NUMERIC.match(s)
    if m:
        a, b, c = int(m[1]), int(m[2]), int(m[3])
        if len(m[1]) == 4:                       # YYYY/MM/DD
            return _safe_date(a, b, c)
        year = c if c > 99 else 2000 + c
        if a > 12 and b <= 12:
            return _safe_date(year, b, a)        # a is day
        if b > 12 and a <= 12:
            return _safe_date(year, a, b)        # b is day
        if a <= 12 and b <= 12:
            if a == b:
                return _safe_date(year, a, b)    # same either way
            if day_first_hint is False:          # MM/DD
                d, amb = _safe_date(year, a, b)
            else:                                # default day-first
                d, amb = _safe_date(year, b, a)
            return (d, True if d else True)
        return (None, True)

    try:                                          # textual ("1 May 2026")
        dt = duparser.parse(s, dayfirst=bool(day_first_hint))
        return (dt.date(), False)
    except (ValueError, OverflowError):
        return (None, True)


def _safe_date(y: int, m: int, d: int) -> tuple[Optional[date], bool]:
    try:
        return (date(y, m, d), False)
    except ValueError:
        return (None, True)


# --- currency ----------------------------------------------------------------
_SYMBOLS = {
    "$": "USD", "US$": "USD", "£": "GBP", "€": "EUR", "₹": "INR",
    "¥": "JPY", "C$": "CAD", "A$": "AUD", "₩": "KRW", "₪": "ILS",
}
_WORDS = {
    "rs": "INR", "inr": "INR", "usd": "USD", "dollar": "USD", "dollars": "USD",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "eur": "EUR", "euro": "EUR",
    "euros": "EUR", "jpy": "JPY", "yen": "JPY", "cad": "CAD", "aud": "AUD",
}


def normalize_currency(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip()
    if s in _SYMBOLS:
        return _SYMBOLS[s]
    low = s.lower().rstrip(".")
    if low in _WORDS:
        return _WORDS[low]
    if re.fullmatch(r"[A-Za-z]{3}", s):           # assume an ISO code
        return s.upper()
    for sym, code in _SYMBOLS.items():            # symbol embedded in a string
        if sym in s:
            return code
    return None


# --- vendor ------------------------------------------------------------------
_LEGAL = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|plc|sarl|gmbh|pvt|pte|co|corp|company|llp|ag|bv|nv)\b\.?",
    re.I,
)


@dataclass
class VendorMatch:
    vendor_id: Optional[str]
    canonical_name: str
    is_new: bool
    score: float = 0.0


def _clean_name(name: str) -> str:
    s = re.sub(r"[.,]", " ", name or "")
    s = _LEGAL.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_vendor(raw: Optional[str], vendors: list[dict],
                     threshold: Optional[int] = None) -> VendorMatch:
    """Match against the vendor master (canonical + aliases) by string similarity.
    Below threshold -> a new vendor with a cleaned proposed canonical name."""
    threshold = threshold if threshold is not None else get_settings().vendor_fuzzy_threshold
    cleaned = _clean_name(raw or "")
    proposed = cleaned.title() if cleaned else (raw or "").strip()

    best_vendor: Optional[dict] = None
    best_score = -1.0
    target = cleaned.lower()
    for v in vendors:
        for key in [v["canonical_name"], *v.get("aliases", [])]:
            score = fuzz.token_sort_ratio(_clean_name(key).lower(), target)
            if score > best_score:
                best_score, best_vendor = score, v

    if best_vendor and best_score >= threshold:
        return VendorMatch(best_vendor["id"], best_vendor["canonical_name"], False, best_score)
    return VendorMatch(None, proposed or (raw or ""), True, max(best_score, 0.0))
