"""Document preprocessing — all deterministic, no LLM.

Responsibilities (§4, §7, R6):
- Decide per page whether it is *digital* (extractable text -> text path) or
  *scanned* (image-only -> vision path).
- Get scanned input safely under Groq's 4MB / 5-image limits: auto-rotate
  (EXIF), deskew, enhance contrast, downscale + recompress.
- Split / rasterize PDFs for the vision path and multi-invoice handling.
"""
from __future__ import annotations

import io
import re
from typing import Sequence

import pdfplumber
from PIL import Image, ImageOps

# Groq vision hard limits (§4). 4MB is the base64-decoded ceiling; we target the
# raw bytes well under it because base64 inflates ~33%.
GROQ_MAX_IMAGE_BYTES = 3_000_000
GROQ_MAX_IMAGES_PER_REQUEST = 5

# A page with at least this many extractable chars is treated as digital.
_MIN_DIGITAL_CHARS = 15


def detect_pdf_page_types(pdf_bytes: bytes, min_chars: int = _MIN_DIGITAL_CHARS) -> list[str]:
    """Per-page 'digital' | 'scanned' based on extractable text (§13 mixed docs)."""
    types: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            types.append("digital" if len(text.strip()) >= min_chars else "scanned")
    return types


def pdf_page_count(pdf_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Concatenated text of a digital PDF (text path input)."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def pdf_to_images(pdf_bytes: bytes, scale: float = 2.0) -> list[bytes]:
    """Rasterize each PDF page to PNG bytes (vision path for scanned PDFs)."""
    import pypdfium2 as pdfium

    out: list[bytes] = []
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        for i in range(len(doc)):
            page = doc[i]
            pil = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            out.append(buf.getvalue())
    finally:
        doc.close()
    return out


# Invoice-number-ish token used to detect document boundaries in a multi-invoice
# PDF (scenario 5). Deterministic; pages with no number attach to the prior
# document (so a single invoice spanning pages stays whole — scenario 6).
_INV_NUM = re.compile(
    r"(?:invoice|inv|bill|credit\s*note|cn)\s*(?:no\.?|number|#|:)?\s*([A-Za-z]{0,5}-?\d[\w-]*)",
    re.I,
)


def split_pdf_by_invoice(pdf_bytes: bytes) -> list[bytes]:
    """Split a multi-invoice PDF into one sub-PDF per detected invoice (scenario 5).

    Boundary signal = a page whose detected invoice number differs from the
    current document's. Pages without a number attach to the current document, so
    a single invoice spanning pages is NOT split (scenario 6). Returns [pdf_bytes]
    unchanged when only one document is present. Only meaningful for digital PDFs;
    scanned multi-page PDFs (no extractable text) return a single document."""
    from pypdf import PdfReader, PdfWriter

    types = detect_pdf_page_types(pdf_bytes)
    if len(types) <= 1:
        return [pdf_bytes]

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_numbers = []
        for page in pdf.pages:
            m = _INV_NUM.search(page.extract_text() or "")
            page_numbers.append(m.group(1).upper() if m else None)

    groups: list[list[int]] = []
    current: list[int] = []
    current_num = None
    for i, num in enumerate(page_numbers):
        if not current:
            current, current_num = [i], num
        elif num is not None and current_num is not None and num != current_num:
            groups.append(current)
            current, current_num = [i], num
        else:
            current.append(i)
            current_num = current_num or num
    if current:
        groups.append(current)

    if len(groups) <= 1:
        return [pdf_bytes]

    reader = PdfReader(io.BytesIO(pdf_bytes))
    out: list[bytes] = []
    for group in groups:
        writer = PdfWriter()
        for idx in group:
            writer.add_page(reader.pages[idx])
        buf = io.BytesIO()
        writer.write(buf)
        out.append(buf.getvalue())
    return out


def chunk_images(images: Sequence, size: int = GROQ_MAX_IMAGES_PER_REQUEST) -> list[list]:
    """Split into batches of <= size (Groq's 5-image-per-request limit, R6)."""
    if size < 1:
        raise ValueError("size must be >= 1")
    return [list(images[i:i + size]) for i in range(0, len(images), size)]


def ensure_under_bytes(image_bytes: bytes, max_bytes: int = GROQ_MAX_IMAGE_BYTES) -> bytes:
    """Recompress / downscale until the JPEG is <= max_bytes (Groq 413 guard).

    Drops quality first, then dimensions — best effort, always returns a valid
    image even if it cannot reach the target (won't loop forever)."""
    if len(image_bytes) <= max_bytes:
        return image_bytes
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    quality = 80
    data = image_bytes
    for _ in range(40):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data
        if quality > 40:
            quality -= 15
            continue
        w, h = img.size
        if min(w, h) <= 150:
            break
        img = img.resize((int(w * 0.8), int(h * 0.8)))
    return data


def _deskew(img: Image.Image) -> Image.Image:
    """Conservative deskew: correct only small rotations (0.5°–15°) so we never
    mangle an already-straight page. Failures are swallowed (best effort)."""
    try:
        import cv2
        import numpy as np

        gray = np.array(img.convert("L"))
        inv = cv2.bitwise_not(gray)
        thr = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thr > 0))
        if coords.shape[0] < 50:
            return img
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if not (0.5 <= abs(angle) <= 15):
            return img
        return img.rotate(angle, expand=True, fillcolor=(255, 255, 255))
    except Exception:
        return img


def preprocess_image(image_bytes: bytes, max_bytes: int = GROQ_MAX_IMAGE_BYTES) -> bytes:
    """Scanned-photo pipeline: auto-rotate (EXIF) -> deskew -> enhance -> cap."""
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)          # honour camera orientation
    img = img.convert("RGB")
    img = _deskew(img)
    img = ImageOps.autocontrast(img)            # lift low-contrast / glare scans
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return ensure_under_bytes(buf.getvalue(), max_bytes)
