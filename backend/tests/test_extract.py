"""Extraction core (§7, R6, R7). The LLM only reads; parsing, repair, and
cross-batch merge are deterministic. We inject a fake LLM at the boundary."""
from decimal import Decimal

import pytest

from backend.extract import (
    ExtractionError,
    extract_from_images,
    extract_from_text,
    merge_extractions,
)
from backend.llm import LLMImage
from backend.schema import DocType, RawExtraction
from backend.tests.fakes import FakeLLM, RaisingLLM

GOOD = (
    '{"doc_type":"invoice","vendor_name":"Acme","invoice_number":"INV-1",'
    '"currency":"USD","subtotal":"100.00","tax_total":"20.00","total":"120.00",'
    '"tax_lines":[{"label":"VAT","rate":"20","amount":"20.00"}],'
    '"line_items":[{"description":"Hosting","amount":"100.00"}],'
    '"category":"Cloud Hosting","_confidence":{"total":0.97}}'
)


def test_text_path_uses_text_model_and_parses():
    llm = FakeLLM([GOOD])
    r = extract_from_text("INVOICE INV-1 ...", llm=llm)
    assert isinstance(r, RawExtraction)
    assert r.total == Decimal("120.00")
    assert r.category == "Cloud Hosting"
    assert llm.calls[0]["model"] == "llama-3.3-70b-versatile"
    assert llm.calls[0]["images"] is None


def test_vision_path_uses_vision_model_and_sends_images():
    llm = FakeLLM([GOOD])
    r = extract_from_images([LLMImage(b"x", "image/png")], llm=llm)
    assert r.doc_type is DocType.invoice
    assert "scout" in llm.calls[0]["model"]
    assert llm.calls[0]["images"] is not None


def test_repair_retry_recovers_from_bad_first_response():
    llm = FakeLLM(["not json at all", GOOD])
    r = extract_from_text("...", llm=llm)
    assert r.total == Decimal("120.00")
    assert len(llm.calls) == 2  # initial + one repair


def test_repair_retry_exhausted_raises():
    llm = FakeLLM(["garbage", "still garbage"])
    with pytest.raises(ExtractionError):
        extract_from_text("...", llm=llm, max_attempts=2)


def test_merge_combines_line_items_and_takes_totals_from_later_batch():
    p1 = RawExtraction.model_validate(
        {"doc_type": "invoice", "vendor_name": "Acme", "invoice_number": "INV-1",
         "line_items": [{"description": "A", "amount": "10"},
                        {"description": "B", "amount": "20"}]}
    )
    p2 = RawExtraction.model_validate(
        {"doc_type": "invoice",
         "line_items": [{"description": "C", "amount": "30"}],
         "subtotal": "60", "tax_total": "12", "total": "72"}
    )
    merged = merge_extractions([p1, p2])
    assert [li.description for li in merged.line_items] == ["A", "B", "C"]
    assert merged.total == Decimal("72")
    assert merged.vendor_name == "Acme"          # first non-null wins
    assert merged.invoice_number == "INV-1"


def test_vision_chunks_over_five_images_and_merges():
    # 6 images -> 2 batches (5 + 1) -> 2 LLM calls -> merged line items.
    r1 = ('{"doc_type":"invoice","invoice_number":"INV-9",'
          '"line_items":[{"description":"A","amount":"10"}]}')
    r2 = ('{"doc_type":"invoice","total":"10","subtotal":"10",'
          '"line_items":[{"description":"B","amount":"0"}]}')
    llm = FakeLLM([r1, r2])
    imgs = [LLMImage(b"x", "image/png") for _ in range(6)]
    merged = extract_from_images(imgs, llm=llm)
    assert len(llm.calls) == 2
    assert [li.description for li in merged.line_items] == ["A", "B"]
    assert merged.total == Decimal("10")
