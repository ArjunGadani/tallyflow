"""Email ingestion (scenarios 5-11). Pure parsing is unit-tested here; IMAP IO
is live-only. Covers attachments, nested forwarded .eml, body-only invoices, and
the inline-image junk filter (R9)."""
import io
from email.message import EmailMessage

from PIL import Image

from backend.ingest_email import extract_documents, parse_email, process_email_bytes
from backend.store import LocalStore
from backend.tests.fakes import FakeLLM
from backend.tests.test_pipeline import CLASSIFY_INV, extract_json, pdf


def _png(w, h) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def email_with_attachment(filename, mime_main, mime_sub, data, body="Please find attached."):
    m = EmailMessage()
    m["Subject"] = "Invoice"
    m["From"] = "vendor@example.com"
    m["Message-ID"] = "<msg-1@example.com>"
    m.set_content(body)
    m.add_attachment(data, maintype=mime_main, subtype=mime_sub, filename=filename)
    return m.as_bytes()


def test_parse_extracts_headers_and_body():
    raw = email_with_attachment("inv.pdf", "application", "pdf", pdf("INV-1"))
    p = parse_email(raw)
    assert p.from_addr == "vendor@example.com"
    assert "msg-1" in p.message_id
    assert "attached" in p.body_text


def test_attachment_becomes_a_document():
    raw = email_with_attachment("inv.pdf", "application", "pdf", pdf("INV-1"))
    docs = extract_documents(parse_email(raw))
    assert len(docs) == 1 and docs[0]["filename"] == "inv.pdf"


def test_nested_forwarded_eml_is_unwrapped():
    inner = EmailMessage()
    inner["Subject"] = "Original Invoice"
    inner.set_content("original")
    inner.add_attachment(pdf("INV-1"), maintype="application", subtype="pdf", filename="inv.pdf")
    outer = EmailMessage()
    outer["Subject"] = "Fwd: Invoice"
    outer["From"] = "me@example.com"
    outer["Message-ID"] = "<fwd-1@example.com>"
    outer.set_content("Forwarded")
    outer.add_attachment(inner)   # content manager sets message/rfc822, preserving structure

    docs = extract_documents(parse_email(outer.as_bytes()))
    assert any(d["filename"] == "inv.pdf" for d in docs)


def test_body_only_invoice_when_no_attachments():
    m = EmailMessage()
    m["Subject"] = "Invoice INV-9"
    m["From"] = "vendor@example.com"
    m["Message-ID"] = "<body-1@example.com>"
    m.set_content("INVOICE INV-9\nTotal: 50.00 GBP")
    docs = extract_documents(parse_email(m.as_bytes()))
    assert len(docs) == 1 and docs[0]["mime"] == "text/plain"


def test_promo_body_only_email_filtered_before_llm():
    # Real Slack-style promo with no attachment: dropped before any Groq call.
    m = EmailMessage()
    m["Subject"] = "Your Workspace has started a free trial of Slack Pro"
    m["From"] = "Slack <no-reply@slack.com>"
    m["Message-ID"] = "<promo-1@slack.com>"
    m.set_content("Your team's free 30 day trial of Slack Pro has started.\n"
                  "Experience premium features.\nUnsubscribe | Manage preferences")
    docs = extract_documents(parse_email(m.as_bytes()))
    assert docs == []  # promo -> no document, no LLM call, no stored row


def test_bulk_header_email_filtered_even_without_promo_words():
    # No keyword match, but List-Unsubscribe marks it bulk (RFC signal) -> dropped.
    m = EmailMessage()
    m["Subject"] = "Updates from your workspace"
    m["From"] = "team@example.com"
    m["Message-ID"] = "<bulk-1@example.com>"
    m["List-Unsubscribe"] = "<https://example.com/u>"
    m.set_content("Here is what happened this week. Thanks for being with us.")
    docs = extract_documents(parse_email(m.as_bytes()))
    assert docs == []  # bulk header + no invoice signal -> dropped before LLM


def test_bulk_header_invoice_still_processed():
    # Bulk header present BUT an invoice signal overrides -> never dropped.
    m = EmailMessage()
    m["Subject"] = "Your invoice"
    m["From"] = "billing@example.com"
    m["Message-ID"] = "<bulk-inv@example.com>"
    m["List-Unsubscribe"] = "<https://example.com/u>"
    m.set_content("Invoice INV-55\nAmount due: $20.00")
    docs = extract_documents(parse_email(m.as_bytes()))
    assert len(docs) == 1  # invoice cue wins over the bulk header


def test_body_only_invoice_from_noreply_still_processed():
    # Conservative: an invoice signal in the body keeps it even from a no-reply.
    m = EmailMessage()
    m["Subject"] = "Receipt"
    m["From"] = "no-reply@stripe.com"
    m["Message-ID"] = "<inv-noreply@stripe.com>"
    m.set_content("Amount due: $42.00\nInvoice number INV-77\nUnsubscribe")
    docs = extract_documents(parse_email(m.as_bytes()))
    assert len(docs) == 1  # invoice cue overrides the unsubscribe marker


def test_logo_attachment_filtered_by_name():
    raw = email_with_attachment("company_logo.png", "image", "png", _png(800, 600))
    docs = extract_documents(parse_email(raw))
    assert docs == []  # junk, no Groq call


def test_tiny_inline_image_filtered_by_dimensions():
    raw = email_with_attachment("image001.png", "image", "png", _png(40, 40))
    docs = extract_documents(parse_email(raw))
    assert docs == []  # tiny -> logo/signature, filtered (R9)


def test_process_email_runs_pipeline():
    store = LocalStore(":memory:")
    llm = FakeLLM([CLASSIFY_INV, extract_json("INV-1", "120", subtotal="100", tax="20")])
    raw = email_with_attachment("inv.pdf", "application", "pdf",
                                pdf("INVOICE INV-1 total 120"))
    counts = process_email_bytes(raw, store, llm, sleep=lambda *_: None)
    assert counts["processed"] == 1
    assert store.count_invoices() == 1
