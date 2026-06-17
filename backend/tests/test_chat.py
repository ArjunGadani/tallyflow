"""Agent loop + grounding guardrail (§7.3). FakeChatLLM can't hallucinate, so the
faithfulness tests SCRIPT wrong answers and assert the guardrail rejects them."""
from decimal import Decimal

import pytest

from backend.chat import _grounded, run_chat
from backend.config import get_settings
from backend.store import LocalStore
from backend.tests.fakes import FakeChatLLM, text_turn, tool_turn


# --- grounding guardrail (unit) — ground against quantity fields, not digit-soup
def test_grounding_ignores_id_and_date_digits():
    results = [("invoice:x", {"invoice_number": "INV-500", "total": "123.45",
                              "invoice_date": "2024-05-12", "source": "invoice:x"})]
    assert _grounded("The total is GBP 123.45.", results) is True
    # 500 appears ONLY inside the invoice number; 5/12 only as month/day → not allowed:
    assert _grounded("You spent GBP 500.", results) is False
    assert _grounded("You spent GBP 12.", results) is False


def test_grounding_allows_year_so_model_can_name_the_period():
    # The system prompt asks the model to name the resolved period; the year token
    # must be groundable from the daterange/date fields, else correct answers reject.
    results = [
        ("daterange", {"date_from": "2026-05-01", "date_to": "2026-05-31",
                       "label": "May 2026", "source": "daterange"}),
        ("summary", {"total_spend": "100", "invoices_counted": "1",
                     "date_from": "2026-05-01", "date_to": "2026-05-31", "source": "summary"}),
    ]
    assert _grounded("In May 2026 you spent GBP 100 across 1 invoice.", results) is True


def test_grounding_percentage_symmetry():
    results = [("events:x", {"confidence_overall": "0.61", "source": "events:x"})]
    assert _grounded("confidence is 61%", results) is True
    assert _grounded("confidence is 0.61", results) is True
    assert _grounded("confidence is 61", results) is True  # no false-reject of bare form


def test_grounding_is_sign_aware():
    results = [("summary", {"total_spend": "50", "source": "summary"})]
    assert _grounded("spend is GBP 50", results) is True
    assert _grounded("a credit of -50", results) is False  # no -50 in the data


def test_grounding_allows_list_counts():
    results = [("vendors", {"vendors": [{"id": "a", "canonical_name": "Globex"},
                                        {"id": "b", "canonical_name": "Acme"},
                                        {"id": "c", "canonical_name": "Initech"}],
                            "source": "vendors"})]
    assert _grounded("There are 3 vendors on record.", results) is True


@pytest.fixture
def store():
    st = LocalStore(":memory:")
    vid = st.upsert_vendor("Globex", default_category="Cloud")
    st.save_invoice({"vendor_id": vid, "doc_type": "invoice", "status": "clean",
                     "invoice_number": "INV-1001", "invoice_date": "2026-05-10",
                     "category": "Cloud", "total": Decimal("100"), "base_total": Decimal("100"),
                     "currency": "GBP", "is_invoice": True, "file_hash": "h1"})
    return st


@pytest.fixture
def settings():
    return get_settings()


def test_loop_runs_tool_then_answers(store, settings):
    llm = FakeChatLLM([
        tool_turn([("get_expense_summary", {})]),
        text_turn("You spent GBP 100 across 1 invoice."),
    ])
    res = run_chat([{"role": "user", "content": "total spend?"}],
                   store=store, llm=llm, settings=settings)
    assert res.grounding_ok is True
    assert "100" in res.answer
    assert "summary" in res.citations
    assert res.tool_trace[0]["name"] == "get_expense_summary"
    assert res.result["kind"] == "summary"
    assert res.result["data"]["total_spend"] == Decimal("100")  # native; endpoint serializes


def test_grounding_rejects_fabricated_number(store, settings):
    # Tool returns 100, but the model claims 999 — must be rejected, not shipped.
    llm = FakeChatLLM([
        tool_turn([("get_expense_summary", {})]),
        text_turn("You spent GBP 999 last month."),
    ])
    res = run_chat([{"role": "user", "content": "spend?"}],
                   store=store, llm=llm, settings=settings)
    assert res.grounding_ok is False
    assert "999" not in res.answer
    assert res.result is None


def test_grounding_rejects_model_side_sum(store, settings):
    # Two real tool numbers summed by the model into a figure no tool returned.
    llm = FakeChatLLM([
        tool_turn([("get_expense_summary", {})]),
        text_turn("Cloud was GBP 100 and Office GBP 50, so GBP 150 total."),
    ])
    res = run_chat([{"role": "user", "content": "spend?"}],
                   store=store, llm=llm, settings=settings)
    assert res.grounding_ok is False  # 50 and 150 are not in the tool result


def test_no_tool_answer_with_numbers_is_rejected(store, settings):
    llm = FakeChatLLM([text_turn("You spent GBP 4242 this year.")])
    res = run_chat([{"role": "user", "content": "spend?"}],
                   store=store, llm=llm, settings=settings)
    assert res.grounding_ok is False


def test_refusal_without_numbers_passes(store, settings):
    llm = FakeChatLLM([text_turn("I can't edit invoices — I'm read-only.")])
    res = run_chat([{"role": "user", "content": "change INV-1 to 500"}],
                   store=store, llm=llm, settings=settings)
    assert res.grounding_ok is True
    assert res.answer.startswith("I can't edit")


def test_resolved_range_surfaced(store, settings):
    llm = FakeChatLLM([
        tool_turn([("resolve_date_range", {"phrase": "last_month"})]),
        tool_turn([("get_expense_summary", {"date_from": "2026-05-01", "date_to": "2026-05-31"})]),
        text_turn("In that period you spent GBP 100."),
    ])
    res = run_chat([{"role": "user", "content": "spend last month?"}],
                   store=store, llm=llm, settings=settings)
    assert res.resolved_range["label"] == "May 2026"
    assert res.grounding_ok is True


def test_iteration_cap(store, settings, monkeypatch):
    monkeypatch.setenv("CHAT_MAX_TOOL_ITERATIONS", "2")
    get_settings.cache_clear()
    s = get_settings()
    # Always asks for another tool → never finishes → cap hit → forced final turn.
    llm = FakeChatLLM([
        tool_turn([("get_review_counts", {})]),
        tool_turn([("get_review_counts", {})]),
        text_turn("Here's what I found."),
    ])
    res = run_chat([{"role": "user", "content": "loop"}], store=store, llm=llm, settings=s)
    assert res.max_iterations_reached is True
    get_settings.cache_clear()


def test_demo_mode_no_llm_call(store, monkeypatch):
    monkeypatch.setenv("CHAT_DEMO_MODE", "true")
    get_settings.cache_clear()
    s = get_settings()

    class Boom:
        def chat(self, *a, **k):
            raise AssertionError("demo mode must not call the LLM")

    res = run_chat([{"role": "user", "content": "what did we spend?"}],
                   store=store, llm=Boom(), settings=s)
    assert res.grounding_ok is True
    assert "100" in res.answer  # grounded from the real tool, no Groq
    get_settings.cache_clear()
