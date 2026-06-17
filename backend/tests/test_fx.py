"""FX conversion is deterministic + date-aware (§6, R15). Rate source injected."""
from datetime import date
from decimal import Decimal

import pytest

from backend.fx import FXError, StaticRateSource, convert_to_base


def test_same_currency_is_identity():
    amt, rate, fxd = convert_to_base(Decimal("100.00"), "GBP", date(2026, 5, 1), base="GBP",
                                     source=StaticRateSource("GBP", {}))
    assert amt == Decimal("100.00")
    assert rate == Decimal("1")


def test_foreign_currency_converted_with_static_rate():
    src = StaticRateSource("GBP", {"USD": Decimal("0.79")})
    amt, rate, fxd = convert_to_base(Decimal("100.00"), "USD", date(2026, 5, 1),
                                     base="GBP", source=src)
    assert amt == Decimal("79.00")
    assert rate == Decimal("0.79")
    assert fxd == date(2026, 5, 1)


def test_unknown_currency_raises():
    src = StaticRateSource("GBP", {"USD": Decimal("0.79")})
    with pytest.raises(FXError):
        convert_to_base(Decimal("10"), "JPY", date(2026, 5, 1), base="GBP", source=src)
