"""Preprocess: deterministic routing + Groq-limit hygiene (§4, R6).
- digital page (has text) -> text path; image-only page -> vision path
- images squeezed under the 4MB cap and chunked to <=5 per request
"""
import io

from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from backend.preprocess import (
    chunk_images,
    detect_pdf_page_types,
    ensure_under_bytes,
    preprocess_image,
)


def _digital_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, "INVOICE INV-1042")
    c.drawString(72, 700, "Acme Web Services   Total: 120.00 USD")
    c.showPage()
    c.save()
    return buf.getvalue()


def _scanned_pdf() -> bytes:
    # An image-only page: no extractable text -> must be detected as scanned.
    img = Image.new("RGB", (400, 300), "white")
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawImage(ImageReader(img_buf), 72, 500, width=200, height=150)
    c.showPage()
    c.save()
    return buf.getvalue()


def _big_png() -> bytes:
    # Random-ish content so it doesn't trivially compress.
    img = Image.effect_noise((2500, 2500), 80).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_digital_pdf_detected_as_digital():
    assert detect_pdf_page_types(_digital_pdf()) == ["digital"]


def test_image_only_pdf_detected_as_scanned():
    assert detect_pdf_page_types(_scanned_pdf()) == ["scanned"]


def test_ensure_under_bytes_shrinks_below_cap():
    big = _big_png()
    assert len(big) > 60_000
    out = ensure_under_bytes(big, 60_000)
    assert len(out) <= 60_000
    Image.open(io.BytesIO(out)).verify()  # still a valid image


def test_chunk_images_respects_five_image_limit():
    items = list(range(12))
    chunks = chunk_images(items, 5)
    assert [len(c) for c in chunks] == [5, 5, 2]


def test_preprocess_image_returns_valid_capped_image():
    out = preprocess_image(_big_png(), max_bytes=200_000)
    assert len(out) <= 200_000
    Image.open(io.BytesIO(out)).verify()


def _two_invoice_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, "INVOICE INV-2001")
    c.drawString(72, 700, "Initech LLC  Total: GBP 80.00")
    c.showPage()
    c.drawString(72, 720, "INVOICE INV-2002")
    c.drawString(72, 700, "Initech LLC  Total: GBP 240.00")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_split_multi_invoice_pdf_into_two():
    from backend.preprocess import split_pdf_by_invoice
    assert len(split_pdf_by_invoice(_two_invoice_pdf())) == 2


def test_split_single_invoice_pdf_unchanged():
    from backend.preprocess import split_pdf_by_invoice
    assert len(split_pdf_by_invoice(_digital_pdf())) == 1
