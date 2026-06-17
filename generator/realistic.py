"""Realistic (but fictional) invoice PDFs for live end-to-end testing.

NOT the synthetic demo set in generate.py — these are polished, vendor-styled
invoices meant to be FORWARDED into the live inbox so the deployed pipeline can
be exercised on lifelike documents. All companies/figures are invented.

They deliberately span the hard cases the deterministic engine must handle:
multi-currency (USD/GBP/EUR/INR -> FX), multi-tax (CGST+SGST), generic fees
(booking/service charge), discounts and shipping. Every total reconciles:
    total = subtotal - discount + fee + shipping + tax

Run:  python -m generator.realistic         (-> realistic_invoices/*.pdf)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

OUT_DIR = "realistic_invoices"
_CUR = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹"}


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money(v, cur) -> str:
    return f"{_CUR.get(cur, '')}{_q(v):,.2f}"


@dataclass
class Line:
    desc: str
    qty: Decimal
    unit: Decimal


@dataclass
class Invoice:
    file: str
    accent: str                      # hex accent colour
    vendor: str
    tagline: str
    vendor_addr: list                # address lines
    vendor_meta: list                # reg/VAT/contact lines
    bill_to: list
    number: str
    date: str
    due: str
    po: str
    currency: str
    terms: str
    lines: list
    tax_label: str                   # e.g. "VAT 20%" or "CGST 9%|SGST 9%"
    tax_rate: Decimal                # combined rate (e.g. 0.20 or 0.18)
    discount: Decimal = Decimal("0")
    fee_label: str = ""
    fee: Decimal = Decimal("0")
    shipping: Decimal = Decimal("0")
    notes: str = ""
    bank: list = field(default_factory=list)
    page: str = "A4"


def _totals(inv: Invoice):
    subtotal = sum((_q(l.qty * l.unit) for l in inv.lines), Decimal("0"))
    base = subtotal - inv.discount + inv.fee + inv.shipping
    tax = _q(base * inv.tax_rate)
    total = _q(base + tax)
    return _q(subtotal), tax, total


def build(inv: Invoice):
    accent = colors.HexColor(inv.accent)
    page = LETTER if inv.page == "LETTER" else A4
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, inv.file)
    doc = SimpleDocTemplate(path, pagesize=page,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Invoice {inv.number}", author=inv.vendor)
    ss = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=ss["Normal"], fontName="Helvetica-Bold",
                       fontSize=20, textColor=accent, leading=22)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=8.5,
                         textColor=colors.HexColor("#6b7280"), leading=12)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.5, leading=12)
    smallR = ParagraphStyle("smallR", parent=small, alignment=TA_RIGHT)
    lab = ParagraphStyle("lab", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=8.5, textColor=colors.HexColor("#374151"), leading=13)
    big = ParagraphStyle("big", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=22, textColor=colors.HexColor("#9ca3af"),
                         alignment=TA_RIGHT, leading=24)
    body = []

    # --- header: vendor (left) + INVOICE label (right) ---
    left = [Paragraph(inv.vendor, H), Paragraph(inv.tagline, sub),
            Spacer(1, 4), Paragraph("<br/>".join(inv.vendor_addr), small),
            Paragraph("<br/>".join(inv.vendor_meta), sub)]
    right = [Paragraph("INVOICE", big), Spacer(1, 2),
             Paragraph(f"<b>{inv.number}</b>", smallR)]
    head = Table([[left, right]], colWidths=[105 * mm, 60 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    body += [head, Spacer(1, 6)]
    body += [Table([[""]], colWidths=[165 * mm],
                   style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 2, accent)])),
             Spacer(1, 10)]

    # --- bill-to (left) + meta (right) ---
    meta_rows = [["Invoice date", inv.date], ["Due date", inv.due],
                 ["PO number", inv.po], ["Terms", inv.terms]]
    meta_tbl = Table([[Paragraph(k, lab), Paragraph(v, smallR)] for k, v in meta_rows],
                     colWidths=[30 * mm, 35 * mm])
    meta_tbl.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"),
                                  ("TOPPADDING", (0, 0), (-1, -1), 1),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    billto = [Paragraph("BILL TO", lab), Spacer(1, 3),
              Paragraph("<br/>".join(inv.bill_to), small)]
    info = Table([[billto, meta_tbl]], colWidths=[100 * mm, 65 * mm])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    body += [info, Spacer(1, 12)]

    # --- line items ---
    data = [["#", "Description", "Qty", "Unit price", "Amount"]]
    for i, l in enumerate(inv.lines, 1):
        data.append([str(i), Paragraph(l.desc, small), f"{_q(l.qty):g}",
                     money(l.unit, inv.currency), money(l.qty * l.unit, inv.currency)])
    items = Table(data, colWidths=[10 * mm, 89 * mm, 16 * mm, 25 * mm, 25 * mm])
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (1, 0), (1, -1), 6),
    ]))
    body += [items, Spacer(1, 8)]

    # --- totals ---
    subtotal, tax, total = _totals(inv)
    trows = [["Subtotal", money(subtotal, inv.currency)]]
    if inv.discount:
        trows.append(["Discount", "-" + money(inv.discount, inv.currency)])
    if inv.fee:
        trows.append([inv.fee_label or "Fee", money(inv.fee, inv.currency)])
    if inv.shipping:
        trows.append(["Shipping", money(inv.shipping, inv.currency)])
    base = subtotal - inv.discount + inv.fee + inv.shipping
    if "|" in inv.tax_label:                       # split tax (e.g. CGST+SGST)
        labels = inv.tax_label.split("|"); half = _q(tax / len(labels))
        for j, lb in enumerate(labels):
            amt = tax - half * (len(labels) - 1) if j == len(labels) - 1 else half
            trows.append([lb, money(amt, inv.currency)])
    else:
        trows.append([inv.tax_label, money(tax, inv.currency)])
    trows.append(["TOTAL DUE", money(total, inv.currency)])
    tt = Table(trows, colWidths=[40 * mm, 35 * mm], hAlign="RIGHT")
    n = len(trows) - 1
    tt.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -2), colors.HexColor("#374151")),
        ("LINEABOVE", (0, n), (-1, n), 1, accent),
        ("FONTNAME", (0, n), (-1, n), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, n), (-1, n), accent), ("FONTSIZE", (0, n), (-1, n), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    body += [tt, Spacer(1, 16)]

    # --- notes + bank + footer ---
    if inv.notes:
        body += [Paragraph(f"<b>Notes.</b> {inv.notes}", small), Spacer(1, 6)]
    if inv.bank:
        body += [Paragraph("PAYMENT DETAILS", lab), Spacer(1, 2),
                 Paragraph("&nbsp;&nbsp;|&nbsp;&nbsp;".join(inv.bank), sub), Spacer(1, 10)]
    body += [Table([[""]], colWidths=[165 * mm],
                   style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5,
                                      colors.HexColor("#e5e7eb"))])), Spacer(1, 4),
             Paragraph(f"Thank you for your business — please reference {inv.number} with payment.",
                       ParagraphStyle("foot", parent=sub, alignment=TA_LEFT))]
    doc.build(body)
    return path, subtotal, tax, total
