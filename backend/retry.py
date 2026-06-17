"""Reliability layer (§8). Each document is a job: transient Groq/network
failures retry with exponential backoff; after N tries (or on a permanent
failure) the job is dead-lettered with its payload retained, never silently
dropped. Idempotency (file_hash + logical keys) makes replaying a run safe.
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Callable, Optional

from backend.config import get_settings
from backend.llm import LLMError
from backend.pipeline import PipelineResult, process_document
from backend.store import Store, get_store


def with_retry(fn: Callable, *, max_tries: Optional[int] = None,
               base_delay: Optional[int] = None, sleep=time.sleep):
    """Call fn(); retry transient LLMErrors with exponential backoff. Permanent
    errors raise immediately; exhausting retries re-raises the last error."""
    s = get_settings()
    max_tries = max_tries or s.retry_max_tries
    base_delay = base_delay or s.retry_base_delay_sec
    last: Optional[Exception] = None
    for attempt in range(1, max_tries + 1):
        try:
            return fn()
        except LLMError as exc:
            last = exc
            if not exc.transient or attempt == max_tries:
                raise
            sleep(base_delay * (2 ** (attempt - 1)))
    raise last  # pragma: no cover


def _store_payload(payload_dir: str, file_bytes: bytes, filename: Optional[str]) -> str:
    os.makedirs(payload_dir, exist_ok=True)
    name = filename or "payload.bin"
    path = os.path.join(payload_dir, f"{hashlib.sha256(file_bytes).hexdigest()[:16]}_{name}")
    with open(path, "wb") as f:
        f.write(file_bytes)
    return path


def run_safely(file_bytes: bytes, filename: Optional[str], mime: Optional[str],
               source: str = "upload", source_ref: Optional[str] = None, *,
               store: Optional[Store] = None, llm=None,
               processor: Callable = process_document, sleep=time.sleep,
               payload_dir: str = "dead_letter_payloads",
               metadata: Optional[dict] = None) -> PipelineResult:
    """Run the pipeline with retry; dead-letter on exhausted/permanent failure."""
    store = store or get_store()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    try:
        return with_retry(
            lambda: processor(file_bytes, filename, mime, source, source_ref,
                              llm=llm, store=store, metadata=metadata),
            sleep=sleep,
        )
    except Exception as exc:
        # ANY terminal failure is dead-lettered, never lost (§2.10, §8): transient
        # LLM errors were already retried by with_retry; corrupt/unsupported files,
        # permanent LLM errors, and unrecoverable extraction all land here.
        payload_path = _store_payload(payload_dir, file_bytes, filename)
        store.add_dead_letter(source_ref or filename, file_hash, str(exc),
                              get_settings().retry_max_tries, payload_path)
        return PipelineResult(None, "dead_letter", "failed", "unknown", False, [],
                              f"dead-lettered after retries: {exc}")


def run_file(file_bytes: bytes, filename: Optional[str], mime: Optional[str],
             source: str = "upload", source_ref: Optional[str] = None, *,
             store: Optional[Store] = None, llm=None, sleep=time.sleep,
             payload_dir: str = "dead_letter_payloads",
             metadata: Optional[dict] = None) -> list[PipelineResult]:
    """Split a multi-invoice file, then run each document resiliently (scenario 5).
    A single-invoice file yields a one-element list."""
    from backend.pipeline import split_documents

    store = store or get_store()
    docs = split_documents(file_bytes, mime, filename)
    return [run_safely(b, n, m, source, source_ref, store=store, llm=llm,
                       sleep=sleep, payload_dir=payload_dir, metadata=metadata)
            for (b, n, m) in docs]


_MIME_BY_EXT = {".pdf": "application/pdf", ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def retry_dead_letter(dl_id: str, *, store: Optional[Store] = None, llm=None,
                      sleep=time.sleep) -> list[PipelineResult]:
    """Replay a dead-lettered document from its stored payload (§30 idempotent
    replay). The old entry is removed first; if it fails again, run_safely
    creates a fresh one — no duplicates."""
    store = store or get_store()
    row = store.get_dead_letter(dl_id)
    if not row:
        raise LookupError("dead-letter entry not found")
    path = row.get("payload_path")
    if not path or not os.path.exists(path):
        raise FileNotFoundError("stored payload missing; cannot retry")

    with open(path, "rb") as f:
        data = f.read()
    # Derive a clean filename: source_ref is "filename" (upload) or "msgid:filename" (email).
    source_ref = row.get("source_ref") or os.path.basename(path)
    filename = source_ref.split(":")[-1] if ":" in source_ref else source_ref
    if not os.path.splitext(filename)[1]:
        filename = os.path.basename(path)
    mime = _MIME_BY_EXT.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")

    store.delete_dead_letter(dl_id)  # clear old; a repeat failure re-dead-letters cleanly
    return run_file(data, filename, mime, source="retry", source_ref=row.get("source_ref"),
                    store=store, llm=llm, sleep=sleep)
