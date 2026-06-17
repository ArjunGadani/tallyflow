"""Single source of truth for configuration (§0).

Every model ID, threshold, tolerance, and secret is defined HERE and nowhere
else. Groq rotates models frequently, so model IDs are env-overridable strings
in one place — never hardcoded across modules. Money tolerances are Decimal so
they compare cleanly against Decimal money values (no float drift).
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Pydantic protects the ``model_`` namespace by default; we intentionally use
    # model_* field names, so disable that protection. Env matching is
    # case-insensitive (MODEL_CLASSIFY -> model_classify).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    # --- Groq (LLM used ONLY for classify / extract / categorize) ---
    groq_api_key: str = ""

    # --- Model IDs: THE one place (§0). ---
    model_classify: str = "llama-3.3-70b-versatile"
    model_extract_text: str = "llama-3.3-70b-versatile"
    model_extract_vision: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    model_chat: str = "llama-3.3-70b-versatile"  # TallyChat tool-calling model (§7.5)
    validate_models_on_startup: bool = False

    # --- TallyChat (read-only conversational assistant) ---
    chat_max_tool_iterations: int = 5      # hard cap on the agentic tool-call loop
    chat_max_tokens: int = 2048            # per-completion ceiling (tabular answers need headroom)
    chat_history_token_budget: int = 3000  # server-authoritative history trim (by tokens, not msgs)
    chat_demo_mode: bool = False           # serve scripted answers with NO Groq call (public demo, §8.5)
    chat_rate_limit_per_min: int = 20      # best-effort per-conversation throttle
    chat_daily_spend_calls: int = 2000     # hard daily Groq-call cap; fails closed (§8.3)

    # --- Storage ---
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_db_url: str = ""
    supabase_storage_bucket: str = "tallyflow-originals"
    store_backend: str = "auto"  # auto | sqlite | supabase
    db_pool_max_size: int = 5    # PgStore connection-pool ceiling (Supabase prod)

    # --- Currency / FX ---
    base_currency: str = "GBP"
    fx_source: str = "frankfurter"  # frankfurter | static
    fx_static_rates: str = ""        # optional JSON fallback

    # --- Confidence / reconciliation (deterministic — §7, R12) ---
    confidence_review_threshold: Decimal = Decimal("0.75")
    totals_tolerance_abs: Decimal = Decimal("0.05")
    totals_tolerance_pct: Decimal = Decimal("0.01")
    # Revision-vs-duplicate band (R2): delta within = duplicate, above = revision.
    revision_tolerance_abs: Decimal = Decimal("0.05")
    revision_tolerance_pct: Decimal = Decimal("0.01")
    vendor_fuzzy_threshold: int = 88  # rapidfuzz 0..100

    # --- Reliability ---
    retry_max_tries: int = 4
    retry_base_delay_sec: int = 2

    # --- Local auto-poll (dev convenience; prod uses the scheduled cron because
    #     Cloud Run scales to zero and can't poll continuously). ---
    auto_poll: bool = False
    poll_interval_sec: int = 30

    # --- Email ingestion (Phase 7) ---
    imap_host: str = "imap.gmail.com"
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # --- Delivery (Phase 8) ---
    slack_webhook: str = ""
    resend_api_key: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    digest_to: str = ""
    digest_from: str = "tallyflow@example.com"

    # --- Dashboard / CORS ---
    cors_origin: str = "http://localhost:5173"
    dashboard_url: str = "http://localhost:5173"

    def configured_model_ids(self) -> list[str]:
        """All Groq model IDs in use — single accessor for startup validation."""
        return [self.model_classify, self.model_extract_text,
                self.model_extract_vision, self.model_chat]

    @property
    def store_is_supabase(self) -> bool:
        """Use Supabase when explicitly chosen, or auto + creds present."""
        if self.store_backend == "supabase":
            return True
        if self.store_backend == "sqlite":
            return False
        return bool(self.supabase_url and self.supabase_service_key)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Use this everywhere instead of constructing Settings()."""
    return Settings()
