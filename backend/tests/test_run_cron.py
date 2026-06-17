"""Scheduled run (§8, §16): poll -> process -> digest -> record the run.
Poll + send are injected so this is testable without IMAP/network."""
from backend.run_cron import run_scheduled
from backend.store import LocalStore


def test_run_records_counts_and_sends_digest():
    store = LocalStore(":memory:")
    calls = {"sent": None}

    def fake_poll(store_, llm_):
        return {"processed": 2, "skipped": 1, "failed": 0}

    def fake_send(store_, counts):
        calls["sent"] = counts
        return {"email": True, "slack": True}

    result = run_scheduled(store, llm=None, poll=fake_poll, send=fake_send)

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["processed"] == 2 and runs[0]["skipped"] == 1 and runs[0]["failed"] == 0
    assert runs[0]["finished_at"] is not None
    assert calls["sent"]["processed"] == 2          # digest got the run counts
    assert result["digest"] == {"email": True, "slack": True}


def test_digest_skipped_when_disabled():
    store = LocalStore(":memory:")
    store.set_setting("digest_enabled", "false")
    calls = {"sent": False}

    def fake_send(store_, counts):
        calls["sent"] = True
        return {"email": True, "slack": True}

    result = run_scheduled(store, llm=None,
                           poll=lambda s, l: {"processed": 0, "skipped": 0, "failed": 0},
                           send=fake_send)
    assert calls["sent"] is False                    # digest NOT sent
    assert result["digest"] == {"skipped": True}
    assert len(store.list_runs()) == 1               # poll/run still recorded
