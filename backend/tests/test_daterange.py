"""Frozen-clock date resolution (§7.2, P0-1) — the model never computes dates."""
from datetime import date

import pytest

from backend.daterange import PHRASES, resolve_date_range

AS_OF = date(2026, 6, 16)  # a Tuesday in Q2


def test_last_month():
    r = resolve_date_range("last_month", AS_OF)
    assert r == {"date_from": "2026-05-01", "date_to": "2026-05-31", "label": "May 2026"}


def test_this_month():
    r = resolve_date_range("this_month", AS_OF)
    assert r["date_from"] == "2026-06-01" and r["date_to"] == "2026-06-30"


def test_this_quarter_is_q2():
    r = resolve_date_range("this_quarter", AS_OF)
    assert r == {"date_from": "2026-04-01", "date_to": "2026-06-30", "label": "Q2 2026"}


def test_last_quarter_is_q1():
    r = resolve_date_range("last_quarter", AS_OF)
    assert r == {"date_from": "2026-01-01", "date_to": "2026-03-31", "label": "Q1 2026"}


def test_ytd_ends_today():
    r = resolve_date_range("ytd", AS_OF)
    assert r["date_from"] == "2026-01-01" and r["date_to"] == "2026-06-16"


def test_last_year():
    r = resolve_date_range("last_year", AS_OF)
    assert r == {"date_from": "2025-01-01", "date_to": "2025-12-31", "label": "2025"}


def test_last_7_days_inclusive():
    r = resolve_date_range("last_7_days", AS_OF)
    assert r["date_from"] == "2026-06-10" and r["date_to"] == "2026-06-16"


def test_all_time_is_open():
    r = resolve_date_range("all_time", AS_OF)
    assert r == {"date_from": None, "date_to": None, "label": "all time"}


def test_year_boundary_last_month():
    r = resolve_date_range("last_month", date(2026, 1, 15))
    assert r == {"date_from": "2025-12-01", "date_to": "2025-12-31", "label": "Dec 2025"}


def test_unknown_phrase_raises():
    with pytest.raises(ValueError):
        resolve_date_range("next_fortnight", AS_OF)


def test_all_phrases_resolve():
    for p in PHRASES:
        resolve_date_range(p, AS_OF)  # must not raise
