"""Base-currency conversion (§6, R15). Deterministic and date-aware: the rate is
fetched as-of the invoice date, not "today". Rate source is pluggable —
Frankfurter (ECB historical, no key) by default, static table as fallback.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Protocol

from backend.config import get_settings


class FXError(Exception):
    pass


class RateSource(Protocol):
    def get_rate(self, from_currency: str, to_currency: str, on: date) -> Optional[Decimal]: ...


class StaticRateSource:
    """rates = {currency: units_of_base_per_1_currency}, for a single base."""

    def __init__(self, base: str, rates: dict):
        self.base = base
        self.rates = {k: Decimal(str(v)) for k, v in rates.items()}

    def get_rate(self, from_currency, to_currency, on) -> Optional[Decimal]:
        if from_currency == to_currency:
            return Decimal("1")
        if to_currency == self.base and from_currency in self.rates:
            return self.rates[from_currency]
        if from_currency == self.base and to_currency in self.rates:
            r = self.rates[to_currency]
            return (Decimal("1") / r) if r else None
        return None


class FrankfurterSource:
    # Frankfurter migrated to api.frankfurter.dev (the old .app host now 301s).
    BASE_URL = "https://api.frankfurter.dev/v1"

    def get_rate(self, from_currency, to_currency, on) -> Optional[Decimal]:
        if from_currency == to_currency:
            return Decimal("1")
        import httpx

        try:
            # follow_redirects so a host move (301) degrades gracefully, not to an error.
            resp = httpx.get(f"{self.BASE_URL}/{on.isoformat()}",
                             params={"from": from_currency, "to": to_currency},
                             timeout=15, follow_redirects=True)
            resp.raise_for_status()
            rate = resp.json().get("rates", {}).get(to_currency)
            return Decimal(str(rate)) if rate is not None else None
        except Exception as exc:                      # network/parse -> FX failure
            raise FXError(f"FX fetch failed for {from_currency}->{to_currency}: {exc}") from exc


def get_default_source() -> RateSource:
    s = get_settings()
    if s.fx_source == "static":
        import json
        rates = json.loads(s.fx_static_rates) if s.fx_static_rates else {}
        return StaticRateSource(s.base_currency, rates)
    return FrankfurterSource()


def convert_to_base(amount: Optional[Decimal], currency: Optional[str], on_date: date,
                    base: Optional[str] = None,
                    source: Optional[RateSource] = None) -> tuple[Optional[Decimal], Optional[Decimal], date]:
    """Return (base_amount, rate, fx_date). Identity when already in base. Raises
    FXError when no rate is available (pipeline flags -> needs_review)."""
    base = base or get_settings().base_currency
    if amount is None:
        return (None, None, on_date)
    if not currency or currency == base:
        return (amount, Decimal("1"), on_date)
    source = source or get_default_source()
    rate = source.get_rate(currency, base, on_date)
    if rate is None:
        raise FXError(f"no FX rate for {currency}->{base} on {on_date}")
    base_amount = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (base_amount, rate, on_date)
