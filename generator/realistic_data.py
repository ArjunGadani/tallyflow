"""The 7 realistic invoices + runner. `python -m generator.realistic_data`."""
from __future__ import annotations

from decimal import Decimal as D

from generator.realistic import Invoice, Line, build, money

BILL_TO = ["TallyFlow Ltd", "Attn: Accounts Payable", "27 Shoreditch High St",
           "London EC1V 9HX, United Kingdom", "VAT GB 412 7755 09"]

INVOICES = [
    Invoice(
        file="01_northwind_cloud_usd.pdf", accent="#0f766e", page="LETTER",
        vendor="Northwind Cloud Services, Inc.", tagline="Managed cloud infrastructure",
        vendor_addr=["500 Townsend Street, Suite 220", "San Francisco, CA 94103, USA"],
        vendor_meta=["billing@northwindcloud.com  ·  +1 (415) 555-0192",
                     "EIN 84-3920175  ·  northwindcloud.com"],
        bill_to=BILL_TO, number="NWC-2026-04417", date="2026-06-02", due="2026-07-02",
        po="PO-TF-3391", currency="USD", terms="Net 30",
        lines=[Line("Standard compute — m5.large instance (730 hrs @ usage)", D("730"), D("0.096")),
               Line("Block storage — 500 GB-month, gp3", D("500"), D("0.10")),
               Line("Outbound data transfer — 1,200 GB", D("1200"), D("0.045")),
               Line("Premium support plan — monthly", D("1"), D("99.00"))],
        tax_label="Sales tax (CA 8.625%)", tax_rate=D("0.08625"),
        notes="Usage billed in arrears for the period 1–31 May 2026.",
        bank=["Bank: First Republic", "Routing: 321081669", "Acct: ****4471", "Wire/ACH accepted"]),

    Invoice(
        file="02_atlas_office_supplies_gbp.pdf", accent="#b45309",
        vendor="Atlas Office Supplies Ltd", tagline="Workplace & stationery solutions since 1998",
        vendor_addr=["Unit 7, Brookfield Trading Estate", "Twickenham TW1 3QS, United Kingdom"],
        vendor_meta=["accounts@atlasoffice.co.uk  ·  +44 20 8744 2210",
                     "Company No. 03561284  ·  VAT GB 661 8841 23"],
        bill_to=BILL_TO, number="ATL-58821", date="2026-06-05", due="2026-06-19",
        po="PO-TF-3402", currency="GBP", terms="Net 14",
        lines=[Line("A4 premium copier paper, 80gsm (box of 5 reams)", D("12"), D("21.50")),
               Line("HP 410X high-yield toner, black", D("4"), D("118.00")),
               Line("Ergonomic mesh task chair — Aria II", D("6"), D("149.00")),
               Line("Whiteboard markers, assorted (pack of 12)", D("10"), D("8.40"))],
        tax_label="VAT 20%", tax_rate=D("0.20"),
        discount=D("95.00"),
        notes="Loyalty discount applied. Goods delivered to reception, signed for.",
        bank=["Barclays Bank", "Sort code: 20-71-64", "Acct: 50847123", "Ref: ATL-58821"]),

    Invoice(
        file="03_meridian_logistics_inr.pdf", accent="#1d4ed8",
        vendor="Meridian Logistics Pvt. Ltd.", tagline="Freight forwarding & customs clearance",
        vendor_addr=["Plot 14, MIDC Industrial Area, Andheri East", "Mumbai 400093, Maharashtra, India"],
        vendor_meta=["billing@meridianlogistics.in  ·  +91 22 4012 8800",
                     "GSTIN 27AAFCM1234R1Z5  ·  PAN AAFCM1234R"],
        bill_to=BILL_TO, number="ML/2026-27/1183", date="2026-06-04", due="2026-06-18",
        po="PO-TF-3398", currency="INR", terms="Net 14",
        lines=[Line("Ocean freight — 1×20ft FCL, Nhava Sheva → Felixstowe", D("1"), D("84500.00")),
               Line("Documentation & customs handling", D("1"), D("6500.00")),
               Line("Container haulage (door pickup)", D("1"), D("9000.00"))],
        tax_label="CGST 9%|SGST 9%", tax_rate=D("0.18"),
        notes="GST levied as CGST + SGST (intra-state). Insurance excluded.",
        bank=["HDFC Bank, Andheri", "IFSC HDFC0000123", "A/C 50200012345678"]),

    Invoice(
        file="04_brightbyte_software_eur.pdf", accent="#6d28d9",
        vendor="BrightByte Software GmbH", tagline="Developer tooling & analytics",
        vendor_addr=["Rosenthaler Straße 40-41", "10178 Berlin, Germany"],
        vendor_meta=["rechnung@brightbyte.de  ·  +49 30 9210 4455",
                     "USt-IdNr. DE298471123  ·  HRB 145820 B"],
        bill_to=BILL_TO, number="BB-2026-000914", date="2026-06-01", due="2026-07-01",
        po="PO-TF-3380", currency="EUR", terms="Net 30",
        lines=[Line("BrightByte Analytics — Team plan, annual (25 seats)", D("25"), D("180.00")),
               Line("Onboarding & data migration (one-time)", D("1"), D("950.00")),
               Line("Priority SLA add-on — annual", D("1"), D("1200.00"))],
        tax_label="USt 19%", tax_rate=D("0.19"),
        notes="Annual subscription 1 Jul 2026 – 30 Jun 2027. Auto-renews unless cancelled.",
        bank=["Deutsche Bank", "IBAN DE89 3704 0044 0532 0130 00", "BIC DEUTDEFF"]),

    Invoice(
        file="05_summit_travel_usd_fee.pdf", accent="#0369a1", page="LETTER",
        vendor="Summit Travel Co.", tagline="Corporate travel management",
        vendor_addr=["1201 Wilshire Blvd, Floor 9", "Los Angeles, CA 90017, USA"],
        vendor_meta=["invoices@summittravel.com  ·  +1 (213) 555-0148", "summittravel.com"],
        bill_to=BILL_TO, number="ST-2026-77310", date="2026-06-06", due="2026-06-21",
        po="PO-TF-3410", currency="USD", terms="Net 15",
        lines=[Line("Round-trip airfare — LHR↔SFO, economy (2 pax)", D("2"), D("842.00")),
               Line("Hotel — The Marker SF, 3 nights", D("3"), D("289.00")),
               Line("Airport transfers (sedan, 4 legs)", D("4"), D("65.00"))],
        tax_label="Occupancy & sales tax", tax_rate=D("0.06"),
        fee_label="Booking & service fee", fee=D("75.00"),
        notes="Trip ref TR-9931. Fees are non-refundable once ticketed.",
        bank=["Wells Fargo", "Routing 121000248", "Acct ****8820"]),

    Invoice(
        file="06_cafe_verde_catering_gbp_fee.pdf", accent="#15803d",
        vendor="Café Verde Catering Ltd", tagline="Event & office catering",
        vendor_addr=["3 Granary Square", "London N1C 4AA, United Kingdom"],
        vendor_meta=["hello@cafeverde.co.uk  ·  +44 20 3691 5520",
                     "Company No. 09812447  ·  VAT GB 284 1190 67"],
        bill_to=BILL_TO, number="CV-2026-2049", date="2026-06-07", due="2026-06-14",
        po="PO-TF-3415", currency="GBP", terms="Net 7",
        lines=[Line("Hot fork buffet — per head (40 guests)", D("40"), D("18.50")),
               Line("Barista coffee station — half day", D("1"), D("180.00")),
               Line("Service staff (2 × 5 hrs)", D("10"), D("16.00"))],
        tax_label="VAT 20%", tax_rate=D("0.20"),
        fee_label="Service charge (12.5%)", fee=D("133.75"),
        notes="Event 12 Jun 2026, on-site. Service charge per agreed terms.",
        bank=["Lloyds Bank", "Sort code 30-96-12", "Acct 71204488", "Ref CV-2026-2049"]),

    Invoice(
        file="07_helix_hosting_usd_discount.pdf", accent="#be123c", page="LETTER",
        vendor="Helix Web Hosting, Inc.", tagline="Performance hosting & domains",
        vendor_addr=["88 Congress Ave, Suite 410", "Austin, TX 78701, USA"],
        vendor_meta=["billing@helixhosting.com  ·  +1 (512) 555-0173", "helixhosting.com"],
        bill_to=BILL_TO, number="HLX-INV-209884", date="2026-06-03", due="2026-07-03",
        po="PO-TF-3387", currency="USD", terms="Net 30",
        lines=[Line("Managed VPS — Pro plan, 12 months", D("12"), D("39.00")),
               Line("Domain registration — tallyflow.io (2 yrs)", D("2"), D("17.50")),
               Line("Wildcard SSL certificate — annual", D("1"), D("129.00")),
               Line("Daily off-site backups — annual", D("1"), D("60.00"))],
        tax_label="Sales tax (TX 8.25%)", tax_rate=D("0.0825"),
        discount=D("70.20"),
        notes="Annual prepay promo: 15% off the VPS plan applied as a discount.",
        bank=["Chase", "Routing 111000614", "Acct ****3092"]),
]


def main():
    print("Generating realistic invoices ->", "realistic_invoices/")
    for inv in INVOICES:
        path, sub, tax, total = build(inv)
        print(f"  {inv.file:42}  {inv.currency}  subtotal {money(sub, inv.currency):>14}"
              f"  tax {money(tax, inv.currency):>12}  total {money(total, inv.currency):>14}")
    print(f"Done — {len(INVOICES)} PDFs.")


if __name__ == "__main__":
    main()
