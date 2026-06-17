"""End-to-end pipeline (§3) with the Groq boundary faked. Proves the §16
acceptance branches: new, idempotent reprocess, revision supersede, credit-note
reduction, non-invoice skip — and that the reconciled summary stays correct."""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from backend.fx import StaticRateSource
from backend.pipeline import process_document
from backend.store import LocalStore
from backend.summary import reconcile_summary
from backend.tests.fakes import FakeLLM

FX = StaticRateSource("GBP", {"USD": Decimal("0.79")})


def pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for i, line in enumerate(text.split("\n")):
        c.drawString(72, 720 - i * 16, line)
    c.showPage()
    c.save()
    return buf.getvalue()


CLASSIFY_INV = '{"doc_type":"invoice","confidence":0.96}'
CLASSIFY_CREDIT = '{"doc_type":"credit_note","confidence":0.93}'
CLASSIFY_NON = '{"doc_type":"non_invoice","confidence":0.88}'


def extract_json(number, total, *, doc_type="invoice", vendor="Acme Ltd",
                 currency="GBP", subtotal=None, tax=None, ref=None, inv_date="2026-05-01"):
    subtotal = subtotal if subtotal is not None else total
    tax = tax if tax is not None else "0"
    parts = [
        f'"doc_type":"{doc_type}"', f'"vendor_name":"{vendor}"',
        f'"invoice_number":"{number}"', f'"invoice_date":"{inv_date}"',
        f'"currency":"{currency}"',
        f'"subtotal":"{subtotal}"', f'"tax_total":"{tax}"', f'"discount":"0"',
        f'"shipping":"0"', f'"total":"{total}"',
        f'"line_items":[{{"description":"Item","amount":"{subtotal}"}}]',
        '"category":"Cloud Hosting"', '"_confidence":{"total":0.95}',
    ]
    if ref:
        parts.append(f'"referenced_invoice_number":"{ref}"')
    if tax not in ("0", 0):
        parts.append(f'"tax_lines":[{{"label":"VAT","rate":"20","amount":"{tax}"}}]')
    return "{" + ",".join(parts) + "}"


def run(store, llm, text, name="doc.pdf"):
    return process_document(pdf(text), name, "application/pdf",
                            store=store, llm=llm, fx_source=FX)


def test_new_invoice_is_stored_and_counted():
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20")])
    res = run(store, llm, "INVOICE INV-1 Acme total 120")
    assert res.branch == "new" and res.status == "clean"
    inv = store.get_invoice(res.invoice_id)
    assert inv["total"] == Decimal("120") and len(inv["line_items"]) == 1
    s = reconcile_summary(store.summary_rows(), "GBP")
    assert s.total_spend == Decimal("120")


def test_reprocess_same_file_is_idempotent():
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20")])
    body = pdf("INVOICE INV-1 total 120")
    a = process_document(body, "x.pdf", "application/pdf", store=store, llm=llm, fx_source=FX)
    b = process_document(body, "x.pdf", "application/pdf", store=store, llm=llm, fx_source=FX)
    assert a.branch == "new" and b.branch == "exact_duplicate"
    assert store.count_invoices() == 1


def test_revision_supersedes_and_only_latest_counts():
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20"),
                   CLASSIFY_INV, extract_json("INV-1", "150", inv_date="2026-05-10")])
    run(store, llm, "INVOICE INV-1 v1 total 120", "v1.pdf")
    res2 = run(store, llm, "INVOICE INV-1 v2 total 150", "v2.pdf")
    assert res2.branch == "revision"
    inv2 = store.get_invoice(res2.invoice_id)
    assert inv2["version"] == 2 and inv2["supersedes_id"]
    s = reconcile_summary(store.summary_rows(), "GBP")
    assert s.total_spend == Decimal("150")          # v1 superseded, excluded


def test_credit_note_reduces_expense():
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20"),
                   CLASSIFY_CREDIT, extract_json("CN-9", "-20", doc_type="credit_note",
                                                 subtotal="-20", ref="INV-1")])
    run(store, llm, "INVOICE INV-1 total 120", "inv.pdf")
    res2 = run(store, llm, "CREDIT NOTE CN-9 ref INV-1 -20", "cn.pdf")
    assert res2.branch == "credit_note"
    inv2 = store.get_invoice(res2.invoice_id)
    assert inv2["credit_of_id"] and inv2["status"] == "credited"
    s = reconcile_summary(store.summary_rows(), "GBP")
    assert s.total_spend == Decimal("100")          # 120 - 20
    assert s.credits_total == Decimal("20")


def test_orphan_credit_flagged_for_review_and_still_subtracts():
    # Credit referencing an invoice we don't have: subtract it (it's real) AND
    # surface it for human linking (R4).
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_CREDIT, extract_json("CN-1", "-30", doc_type="credit_note",
                                                 subtotal="-30", ref="INV-NOPE")])
    res = run(store, llm, "CREDIT NOTE CN-1 ref INV-NOPE -30", "cn.pdf")
    assert res.branch == "credit_orphan"
    inv = store.get_invoice(res.invoice_id)
    assert inv["status"] == "needs_review"
    assert any(i["id"] == res.invoice_id for i in store.review_queue())
    s = reconcile_summary(store.summary_rows(), "GBP")
    assert s.credits_total == Decimal("30")          # still subtracts


def test_non_invoice_is_skipped():
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_NON])
    res = run(store, llm, "TERMS AND CONDITIONS blah blah")
    assert res.branch == "non_invoice" and res.is_invoice is False
    s = reconcile_summary(store.summary_rows(), "GBP")
    assert s.total_spend == Decimal("0")


def two_invoice_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, "INVOICE INV-2001")
    c.drawString(72, 700, "Initech  Total GBP 80.00")
    c.showPage()
    c.drawString(72, 720, "INVOICE INV-2002")
    c.drawString(72, 700, "Initech  Total GBP 240.00")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_multi_invoice_pdf_split_into_two():
    from backend.retry import run_file
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-2001", "80"),
                   CLASSIFY_INV, extract_json("INV-2002", "240")])
    results = run_file(two_invoice_pdf(), "multi.pdf", "application/pdf",
                       store=store, llm=llm, sleep=lambda *_: None)
    assert len(results) == 2
    assert store.count_invoices() == 2
    assert {r.branch for r in results} == {"new"}


def test_corrupt_pdf_is_dead_lettered_not_crash(tmp_path):
    from backend.retry import run_file
    store = LocalStore(":memory:")
    results = run_file(b"%PDF-1.4 broken not a real pdf", "corrupt.pdf", "application/pdf",
                       store=store, llm=FakeLLM([]), sleep=lambda *_: None,
                       payload_dir=str(tmp_path))
    assert results[0].branch == "dead_letter"
    assert len(store.list_dead_letter()) == 1


def test_email_metadata_and_timestamps_on_events():
    from backend.pipeline import process_document
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20")])
    res = process_document(pdf("INVOICE INV-1 total 120"), "inv.pdf", "application/pdf",
                           source="email", store=store, llm=llm, fx_source=FX,
                           metadata={"email_date": "2026-05-01T09:00:00+00:00", "email_from": "v@x.com"})
    events = store.get_invoice(res.invoice_id)["events"]
    received = next(e for e in events if e["type"] == "received")
    assert received["detail"]["email_date"] == "2026-05-01T09:00:00+00:00"
    assert received["detail"]["email_from"] == "v@x.com"
    assert all(e["ts"] for e in events)              # every step carries an emit-time ts


def test_foreign_currency_converted_to_base():
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-USD", "100", currency="USD")])
    res = run(store, llm, "INVOICE INV-USD total 100 USD")
    inv = store.get_invoice(res.invoice_id)
    assert inv["currency"] == "USD"
    assert inv["base_currency"] == "GBP"
    assert inv["base_total"] == Decimal("79.00")     # 100 * 0.79
    assert inv["fx_rate"] == Decimal("0.79")
