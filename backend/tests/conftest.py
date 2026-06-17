"""Hermetic test environment.

Tests must not depend on the developer's real .env (which carries live creds and
a configurable BASE_CURRENCY). This autouse fixture pins the settings the tests
assume — GBP base, SQLite store — and clears the cached Settings so every test
sees them, regardless of what .env contains.
"""
import pytest

from backend.config import get_settings


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch):
    monkeypatch.setenv("BASE_CURRENCY", "GBP")
    monkeypatch.setenv("STORE_BACKEND", "sqlite")
    monkeypatch.setenv("AUTO_POLL", "false")  # never spawn the live poller in tests
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
