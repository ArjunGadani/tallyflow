"""Normalization is deterministic (§0): dates->ISO with ambiguity flagged,
currency->ISO, vendor->canonical via fuzzy match (not LLM)."""
from datetime import date

from backend.normalize import normalize_currency, normalize_date, normalize_vendor


# --- dates (scenario 19) -----------------------------------------------------
def test_iso_date_is_unambiguous():
    assert normalize_date("2026-05-01") == (date(2026, 5, 1), False)


def test_day_over_12_resolves_day_first():
    assert normalize_date("13/04/2026") == (date(2026, 4, 13), False)


def test_value_over_12_in_second_slot_resolves_month_first():
    assert normalize_date("04/13/2026") == (date(2026, 4, 13), False)


def test_ambiguous_date_uses_hint_and_flags():
    d, amb = normalize_date("04/05/2026", day_first_hint=True)
    assert d == date(2026, 5, 4) and amb is True
    d2, amb2 = normalize_date("04/05/2026", day_first_hint=False)
    assert d2 == date(2026, 4, 5) and amb2 is True


def test_identical_interpretations_not_ambiguous():
    assert normalize_date("05/05/2026") == (date(2026, 5, 5), False)


def test_textual_date():
    assert normalize_date("1 May 2026") == (date(2026, 5, 1), False)


def test_unparseable_date_flagged():
    assert normalize_date("not a date") == (None, True)


# --- currency (scenario 20) --------------------------------------------------
def test_currency_symbols_and_codes():
    assert normalize_currency("$") == "USD"
    assert normalize_currency("£") == "GBP"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("₹") == "INR"
    assert normalize_currency("Rs.") == "INR"
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("EUR") == "EUR"
    assert normalize_currency(None) is None


# --- vendor (scenario 15) ----------------------------------------------------
VENDORS = [
    {"id": "v1", "canonical_name": "Amazon Web Services",
     "aliases": ["AWS", "AWS EMEA SARL"]},
    {"id": "v2", "canonical_name": "Office Depot", "aliases": []},
]


def test_vendor_alias_match():
    m = normalize_vendor("AWS EMEA SARL", VENDORS)
    assert m.vendor_id == "v1" and m.is_new is False


def test_vendor_fuzzy_match_ignoring_legal_suffix():
    m = normalize_vendor("Amazon Web Services, Inc.", VENDORS)
    assert m.vendor_id == "v1" and m.is_new is False


def test_unknown_vendor_is_new():
    m = normalize_vendor("Totally Different Co", VENDORS)
    assert m.vendor_id is None and m.is_new is True
    assert m.canonical_name  # a cleaned canonical name is proposed


def test_no_vendors_yields_new():
    m = normalize_vendor("Acme", [])
    assert m.is_new is True
