"""Scheduled entrypoint (§16.10). Runs INSIDE the GitHub Actions runner (Q1) so
Cloud Run stays cold and the shared free tier is preserved. Polls the inbox,
runs the resilient pipeline, records the run, and sends the Email + Slack digest.

Run with:  python -m backend.run_cron
"""
from __future__ import annotations

import logging

from backend.digest import send_digest
from backend.ingest_email import poll_and_process
from backend.llm import get_llm
from backend.store import Store, get_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tallyflow.cron")


def run_scheduled(store: Store, llm=None, *, poll=poll_and_process, send=send_digest) -> dict:
    """Poll -> process -> record run -> digest. poll/send injected for tests."""
    run_id = store.start_run("scheduled")
    counts = poll(store, llm)
    store.finish_run(run_id, counts["processed"], counts["skipped"], counts["failed"])
    # Digest is user-toggleable from the dashboard (default on). When off, the
    # poll/process still runs hourly — only the email + Slack digest is muted.
    digest_on = store.get_setting("digest_enabled", "true") != "false"
    sent = send(store, counts) if digest_on else {"skipped": True}
    logger.info("scheduled run %s: %s, digest=%s", run_id, counts, sent)
    return {"run_id": run_id, **counts, "digest": sent}


def main() -> None:
    store = get_store()
    llm = get_llm()
    run_scheduled(store, llm)


if __name__ == "__main__":
    main()
