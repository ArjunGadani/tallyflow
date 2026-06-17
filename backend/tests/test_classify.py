"""Classification (§7): a deterministic junk pre-filter spares Groq calls on
logos/signatures (R9), then the LLM decides invoice / credit_note / non_invoice.
Unknown/garbage answers fail safe to non_invoice (never store junk as expense)."""
from backend.classify import classify_document, is_probably_junk
from backend.llm import LLMImage
from backend.schema import DocType
from backend.tests.fakes import FakeLLM


def test_junk_filter_flags_tiny_images_and_known_names():
    assert is_probably_junk("logo.png", "image/png", 60, 60) is True
    assert is_probably_junk("company_signature.jpg", "image/jpeg", 400, 120) is True
    assert is_probably_junk("invite.ics", "text/calendar", None, None) is True
    # A full invoice page is not junk.
    assert is_probably_junk("invoice_april.pdf", "application/pdf", 1700, 2200) is False


def test_classify_text_uses_classify_model():
    llm = FakeLLM(['{"doc_type": "invoice", "confidence": 0.95}'])
    res = classify_document(text="INVOICE INV-1042 total 120.00", llm=llm)
    assert res.doc_type is DocType.invoice
    assert res.is_invoice is True
    assert llm.calls[0]["model"] == "llama-3.3-70b-versatile"  # text classify model
    assert llm.calls[0]["images"] is None


def test_classify_image_uses_vision_model():
    llm = FakeLLM(['{"doc_type": "credit_note", "confidence": 0.9}'])
    res = classify_document(images=[LLMImage(b"x", "image/png")], llm=llm)
    assert res.doc_type is DocType.credit_note
    assert res.is_invoice is True  # credit notes are stored (as credits)
    assert "scout" in llm.calls[0]["model"]  # vision model id


def test_classify_handles_fenced_json():
    llm = FakeLLM(['```json\n{"doc_type": "non_invoice", "confidence": 0.8}\n```'])
    res = classify_document(text="Terms and conditions ...", llm=llm)
    assert res.doc_type is DocType.non_invoice
    assert res.is_invoice is False


def test_unknown_doc_type_fails_safe_to_non_invoice():
    llm = FakeLLM(['{"doc_type": "banana", "confidence": 0.5}'])
    res = classify_document(text="???", llm=llm)
    assert res.doc_type is DocType.non_invoice
    assert res.is_invoice is False
