"""Reliability (§8): transient failures retry with backoff; permanent ones
don't; exhausted/permanent failures dead-letter with the payload — never lost."""
from backend.extract import ExtractionError
from backend.llm import LLMError
from backend.retry import run_safely, with_retry
from backend.store import LocalStore
from backend.tests.fakes import FakeLLM


def test_succeeds_first_try():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    assert with_retry(fn, max_tries=4, sleep=lambda *_: None) == "ok"
    assert calls["n"] == 1


def test_transient_retries_then_succeeds():
    calls = {"n": 0}
    slept = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMError("429", transient=True)
        return "ok"

    assert with_retry(fn, max_tries=4, base_delay=1, sleep=slept.append) == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2          # backoff between the failed attempts


def test_transient_exhausts_and_raises():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise LLMError("429", transient=True)

    try:
        with_retry(fn, max_tries=3, sleep=lambda *_: None)
        assert False, "should have raised"
    except LLMError:
        pass
    assert calls["n"] == 3


def test_permanent_error_does_not_retry():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise LLMError("bad request", transient=False)

    try:
        with_retry(fn, max_tries=4, sleep=lambda *_: None)
        assert False
    except LLMError:
        pass
    assert calls["n"] == 1


def test_dead_letter_on_repeated_failure(tmp_path):
    store = LocalStore(":memory:")

    def always_transient(*a, **k):
        raise LLMError("429", transient=True)

    res = run_safely(b"payload-bytes", "bad.pdf", "application/pdf",
                     store=store, llm=None, processor=always_transient,
                     sleep=lambda *_: None, payload_dir=str(tmp_path))
    assert res.branch == "dead_letter" and res.status == "failed"
    dl = store.list_dead_letter()
    assert len(dl) == 1 and dl[0]["error"]


def test_dead_letter_on_permanent_extraction_error(tmp_path):
    store = LocalStore(":memory:")

    def always_extraction_error(*a, **k):
        raise ExtractionError("unrecoverable")

    res = run_safely(b"bytes", "x.pdf", "application/pdf", store=store, llm=None,
                     processor=always_extraction_error, sleep=lambda *_: None,
                     payload_dir=str(tmp_path))
    assert res.branch == "dead_letter"
    assert store.list_dead_letter()[0]["error"]


def test_get_and_delete_dead_letter():
    store = LocalStore(":memory:")
    did = store.add_dead_letter("x.pdf", "h", "boom", 4, "/tmp/x")
    assert store.get_dead_letter(did)["error"] == "boom"
    store.delete_dead_letter(did)
    assert store.get_dead_letter(did) is None
    assert store.list_dead_letter() == []


def test_retry_dead_letter_succeeds_and_clears_entry(tmp_path):
    from backend.retry import retry_dead_letter
    from backend.tests.test_pipeline import CLASSIFY_INV, extract_json, pdf

    store = LocalStore(":memory:")
    payload = tmp_path / "inv.pdf"
    payload.write_bytes(pdf("INVOICE INV-1 total 120"))
    did = store.add_dead_letter("inv.pdf", "h", "transient outage", 4, str(payload))

    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20")])
    results = retry_dead_letter(did, store=store, llm=llm, sleep=lambda *_: None)
    assert results[0].branch == "new"
    assert store.count_invoices() == 1
    assert store.get_dead_letter(did) is None        # old entry cleared
    assert store.list_dead_letter() == []            # success -> no new entry


def test_retry_still_corrupt_redeadletters_without_duplicate(tmp_path):
    from backend.retry import retry_dead_letter

    store = LocalStore(":memory:")
    payload = tmp_path / "corrupt.pdf"
    payload.write_bytes(b"%PDF-1.4 broken not a real pdf")
    did = store.add_dead_letter("corrupt.pdf", "h", "PDFSyntaxError", 4, str(payload))

    results = retry_dead_letter(did, store=store, llm=FakeLLM([]), sleep=lambda *_: None)
    assert results[0].branch == "dead_letter"
    dl = store.list_dead_letter()
    assert len(dl) == 1 and dl[0]["id"] != did       # old removed, one fresh entry
    assert store.count_invoices() == 0


def test_dead_letter_on_any_exception(tmp_path):
    # Corrupt/unsupported files raise non-LLM errors (e.g. PDFSyntaxError ->
    # ValueError-like). These must dead-letter, not crash the batch (§2.10).
    store = LocalStore(":memory:")

    def boom(*a, **k):
        raise ValueError("corrupt / unreadable file")

    res = run_safely(b"x", "corrupt.pdf", "application/pdf", store=store, llm=None,
                     processor=boom, sleep=lambda *_: None, payload_dir=str(tmp_path))
    assert res.branch == "dead_letter" and res.status == "failed"
    assert len(store.list_dead_letter()) == 1
