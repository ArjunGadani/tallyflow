"""Realistic-but-fake document generator (§13). Exercises EVERY hard case in §2
so the pipeline can be proven end-to-end (and demoed) without real invoices.

Outputs to sample_docs/ plus a manifest.json describing each file and the
scenario + relationships it exercises (used to assert behaviour once GROQ_API_KEY
is set and the docs are run live).
"""
from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


@dataclass
class Manifest:
    items: list = field(default_factory=list)

    def add(self, file, scenario, **meta):
        self.items.append({"file": file, "scenario": scenario, **meta})


def _invoice_pdf(*, title="INVOICE", vendor="Globex Cloud Ltd", number="INV-1001",
                 date="2026-05-01", currency="GBP", lines=None, taxes=None,
                 discount="0.00", shipping="0.00", total="120.00",
                 reference=None) -> bytes:
    lines = lines or [("Cloud hosting", "1", "100.00", "100.00")]
    taxes = taxes or [("VAT 20%", "20.00")]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, title)
    c.setFont("Helvetica", 11)
    y -= 30
    c.drawString(50, y, f"{vendor}")
    y -= 16
    c.drawString(50, y, f"Invoice No: {number}     Date: {date}     Currency: {currency}")
    if reference:
        y -= 16
        c.drawString(50, y, f"Against Invoice: {reference}")
    y -= 30
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Description")
    c.drawString(300, y, "Qty")
    c.drawString(360, y, "Unit")
    c.drawString(450, y, "Amount")
    c.setFont("Helvetica", 10)
    for desc, qty, unit, amt in lines:
        y -= 16
        c.drawString(50, y, str(desc))
        c.drawString(300, y, str(qty))
        c.drawString(360, y, str(unit))
        c.drawString(450, y, f"{currency} {amt}")
    y -= 24
    c.drawString(360, y, "Discount")
    c.drawString(450, y, f"{currency} {discount}")
    y -= 16
    c.drawString(360, y, "Shipping")
    c.drawString(450, y, f"{currency} {shipping}")
    for label, amt in taxes:
        y -= 16
        c.drawString(360, y, str(label))
        c.drawString(450, y, f"{currency} {amt}")
    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(360, y, "TOTAL")
    c.drawString(450, y, f"{currency} {total}")
    c.showPage()
    c.save()
    return buf.getvalue()


def _scanned_image(text_lines: list[str], rotate: int = 4) -> bytes:
    """A 'scanned' invoice: rendered text, rotated + noisy -> vision path."""
    img = Image.new("RGB", (1000, 1300), "white")
    d = ImageDraw.Draw(img)
    y = 60
    for line in text_lines:
        d.text((70, y), line, fill="black")
        y += 40
    img = img.rotate(rotate, expand=True, fillcolor=(255, 255, 255))
    noise = Image.effect_noise(img.size, 18).convert("RGB")
    img = Image.blend(img, noise, 0.06)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _terms_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 800, "TERMS AND CONDITIONS")
    c.setFont("Helvetica", 10)
    c.drawString(50, 770, "These terms govern the supply of services. No amounts are billed herein.")
    c.showPage()
    c.save()
    return buf.getvalue()


def generate_all(out_dir: str = "sample_docs") -> Manifest:
    os.makedirs(out_dir, exist_ok=True)
    m = Manifest()

    def write(name, data):
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        return name

    # 1. clean digital invoice (text path)
    base = _invoice_pdf(number="INV-1001", total="120.00")
    write("01_clean_invoice.pdf", base)
    m.add("01_clean_invoice.pdf", "clean_digital", doc_type="invoice", expect="new")

    # 2. exact duplicate (identical bytes)
    write("02_exact_duplicate.pdf", base)
    m.add("02_exact_duplicate.pdf", "exact_duplicate", expect="exact_duplicate", of="01_clean_invoice.pdf")

    # 3. logical duplicate (same invoice, re-exported -> different bytes)
    write("03_logical_duplicate.pdf",
          _invoice_pdf(number="INV-1001", total="120.00", vendor="Globex Cloud Limited"))
    m.add("03_logical_duplicate.pdf", "logical_duplicate", expect="logical_duplicate", of="01_clean_invoice.pdf")

    # 4. revised invoice v2 (same number, changed total/date)
    write("04_revision_v2.pdf",
          _invoice_pdf(number="INV-1001", date="2026-05-09", total="150.00",
                       lines=[("Cloud hosting", "1", "125.00", "125.00")],
                       taxes=[("VAT 20%", "25.00")]))
    m.add("04_revision_v2.pdf", "revision", expect="revision", supersedes="01_clean_invoice.pdf")

    # 5. credit note referencing the original
    write("05_credit_note.pdf",
          _invoice_pdf(title="CREDIT NOTE", number="CN-5001", reference="INV-1001",
                       total="-20.00", lines=[("Service credit", "1", "-20.00", "-20.00")],
                       taxes=[("VAT 20%", "0.00")]))
    m.add("05_credit_note.pdf", "credit_note", expect="credit_note", credit_of="INV-1001")

    # 6. multi-invoice PDF (two invoices, one file)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for n, t in [("INV-2001", "80.00"), ("INV-2002", "240.00")]:
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 800, f"INVOICE {n}")
        c.setFont("Helvetica", 11)
        c.drawString(50, 770, f"Initech LLC   Total: GBP {t}")
        c.showPage()
    c.save()
    write("06_multi_invoice.pdf", buf.getvalue())
    m.add("06_multi_invoice.pdf", "multi_invoice", expect="split_into_2")

    # 7. non-invoice (terms page)
    write("07_non_invoice.pdf", _terms_pdf())
    m.add("07_non_invoice.pdf", "non_invoice", expect="non_invoice")

    # 8. totals mismatch (subtotal+tax != total)
    write("08_totals_mismatch.pdf",
          _invoice_pdf(number="INV-3001", total="999.00",
                       lines=[("Widget", "2", "50.00", "100.00")],
                       taxes=[("VAT 20%", "20.00")]))
    m.add("08_totals_mismatch.pdf", "totals_mismatch", expect="needs_review")

    # 9. ambiguous date (04/05/2026)
    write("09_ambiguous_date.pdf",
          _invoice_pdf(number="INV-3101", date="04/05/2026", total="60.00",
                       lines=[("Consulting", "1", "50.00", "50.00")],
                       taxes=[("VAT 20%", "10.00")]))
    m.add("09_ambiguous_date.pdf", "ambiguous_date", expect="needs_review_or_flag")

    # 10. foreign currency (USD) + multi-tax handled below
    write("10_foreign_currency.pdf",
          _invoice_pdf(number="INV-4001", currency="USD", total="118.00",
                       lines=[("API credits", "1", "100.00", "100.00")],
                       taxes=[("Sales tax 18%", "18.00")]))
    m.add("10_foreign_currency.pdf", "foreign_currency", expect="base_conversion", currency="USD")

    # 11. multi-tax (CGST + SGST)
    write("11_multi_tax_gst.pdf",
          _invoice_pdf(number="INV-5001", currency="INR", total="118.00",
                       lines=[("Software", "1", "100.00", "100.00")],
                       taxes=[("CGST 9%", "9.00"), ("SGST 9%", "9.00")]))
    m.add("11_multi_tax_gst.pdf", "multi_tax", expect="two_tax_lines", currency="INR")

    # 12. scanned / rotated image (vision path)
    write("12_scanned_invoice.png",
          _scanned_image(["INVOICE INV-6001", "Umbrella Supplies Co",
                          "Date: 2026-05-02", "Subtotal: 200.00", "VAT 20%: 40.00",
                          "TOTAL: GBP 240.00"]))
    m.add("12_scanned_invoice.png", "scanned_image", expect="vision_path", doc_type="invoice")

    # 13. corrupt file
    write("13_corrupt.pdf", b"%PDF-1.4 broken \x00\x01 not a real pdf")
    m.add("13_corrupt.pdf", "corrupt", expect="failed_or_dead_letter")

    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(m.items, f, indent=2)
    return m


if __name__ == "__main__":
    mani = generate_all()
    print(f"generated {len(mani.items)} documents -> sample_docs/")
