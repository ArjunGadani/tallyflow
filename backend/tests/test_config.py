"""Config is the ONE place model IDs + thresholds live (§0). Test that contract."""
from decimal import Decimal

from backend.config import Settings


def test_default_model_ids_match_spec():
    s = Settings(_env_file=None)
    assert s.model_classify == "llama-3.3-70b-versatile"
    assert s.model_extract_text == "llama-3.3-70b-versatile"
    assert s.model_extract_vision == "meta-llama/llama-4-scout-17b-16e-instruct"


def test_env_overrides_model_id(monkeypatch):
    monkeypatch.setenv("MODEL_EXTRACT_VISION", "some/new-vision-model")
    s = Settings(_env_file=None)
    assert s.model_extract_vision == "some/new-vision-model"


def test_money_tolerances_are_decimal_not_float():
    # Money math is deterministic Decimal (§0). Tolerances must be Decimal too,
    # or comparisons against Decimal totals raise/round wrong.
    s = Settings(_env_file=None)
    assert isinstance(s.totals_tolerance_abs, Decimal)
    assert isinstance(s.revision_tolerance_abs, Decimal)


def test_base_currency_and_threshold_defaults():
    s = Settings(_env_file=None)
    assert s.base_currency == "GBP"
    assert Decimal("0") < s.confidence_review_threshold <= Decimal("1")


def test_groq_models_list_single_source():
    # All model IDs (incl. chat) reachable from one accessor (no hardcoding elsewhere).
    s = Settings(_env_file=None)
    models = s.configured_model_ids()
    assert s.model_chat in models
    assert set(models) == {
        s.model_classify,
        s.model_extract_text,
        s.model_extract_vision,
        s.model_chat,
    }


def test_chat_defaults_and_env_override(monkeypatch):
    s = Settings(_env_file=None)
    assert s.chat_max_tool_iterations == 5
    assert s.chat_demo_mode is False
    monkeypatch.setenv("CHAT_DEMO_MODE", "true")
    monkeypatch.setenv("MODEL_CHAT", "some/chat-model")
    s2 = Settings(_env_file=None)
    assert s2.chat_demo_mode is True
    assert s2.model_chat == "some/chat-model"
