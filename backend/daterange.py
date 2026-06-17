"""Deterministic relative-date resolution (§7.2, P0-1).

The chat model has no clock and must NEVER do calendar arithmetic. It names a
relative period as an enum; THIS code resolves it to concrete ISO dates anchored
to the server clock. Pure function, fully testable with a frozen `as_of`.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from dateutil.relativedelta import relativedelta

# The enum the model is allowed to pass. Keep in sync with the tool's JSON schema.
PHRASES = (
    "this_month", "last_month", "this_quarter", "last_quarter",
    "this_year", "last_year", "ytd", "last_7_days", "last_30_days", "all_time",
)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _eom(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _month_label(d: date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.year}"


def resolve_date_range(phrase: str, as_of: Optional[date] = None) -> dict:
    """Resolve a relative-period enum to {date_from, date_to, label}.

    Dates are ISO strings (or None for all_time). Raises ValueError on an unknown
    phrase so a bad model arg surfaces, never a silent wrong window."""
    today = as_of or date.today()
    p = (phrase or "").strip().lower()

    if p == "this_month":
        start = today.replace(day=1)
        return _pack(start, _eom(today), _month_label(today))
    if p == "last_month":
        lm = today.replace(day=1) - relativedelta(months=1)
        return _pack(lm, _eom(lm), _month_label(lm))
    if p in ("this_quarter", "last_quarter"):
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        q_start = today.replace(month=q_start_month, day=1)
        if p == "last_quarter":
            q_start = q_start - relativedelta(months=3)
        q_end = _eom(q_start + relativedelta(months=2))
        q_num = (q_start.month - 1) // 3 + 1
        return _pack(q_start, q_end, f"Q{q_num} {q_start.year}")
    if p == "this_year":
        return _pack(today.replace(month=1, day=1), today.replace(month=12, day=31), str(today.year))
    if p == "last_year":
        y = today.year - 1
        return _pack(date(y, 1, 1), date(y, 12, 31), str(y))
    if p == "ytd":
        return _pack(today.replace(month=1, day=1), today, f"YTD {today.year}")
    if p == "last_7_days":
        return _pack(today - relativedelta(days=6), today, "last 7 days")
    if p == "last_30_days":
        return _pack(today - relativedelta(days=29), today, "last 30 days")
    if p == "all_time":
        return {"date_from": None, "date_to": None, "label": "all time"}

    raise ValueError(f"unknown date-range phrase: {phrase!r}")


def _pack(start: date, end: date, label: str) -> dict:
    return {"date_from": start.isoformat(), "date_to": end.isoformat(), "label": label}
