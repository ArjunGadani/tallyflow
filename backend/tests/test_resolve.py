"""Resolution engine (§6) — the heart. Pure deterministic decision over the
incoming invoice + already-fetched existing candidates. Covers the reordering
(R1: credit notes dedup too), the revision-vs-duplicate tolerance band (R2),
the date-ordering guard (R3), and orphan credits (R4)."""
from datetime import date
from decimal import Decimal

from backend.resolve import ExistingInvoice, IncomingInvoice, resolve
from backend.schema import DocType


def inc(**o):
    base = dict(file_hash="h-new", doc_type=DocType.invoice, vendor_id="v1",
                invoice_number="INV-1", invoice_date=date(2026, 5, 1),
                total=Decimal("120.00"), referenced_invoice_number=None)
    base.update(o)
    return IncomingInvoice(**base)


def ex(**o):
    base = dict(id="e1", doc_type=DocType.invoice, vendor_id="v1",
                invoice_number="INV-1", invoice_date=date(2026, 5, 1),
                total=Decimal("120.00"), version=1, status="clean",
                file_hash="h-old", referenced_invoice_number=None)
    base.update(o)
    return ExistingInvoice(**base)


def test_exact_duplicate_by_hash():
    out = resolve(inc(), existing_by_hash=ex(id="e1"), candidates=[])
    assert out.branch == "exact_duplicate"
    assert out.link_to_id == "e1"


def test_logical_duplicate_identical():
    out = resolve(inc(), existing_by_hash=None, candidates=[ex()])
    assert out.branch == "logical_duplicate"
    assert out.link_to_id == "e1"


def test_revision_supersedes_prior():
    # same vendor+number, different total, same-or-newer date -> revision v2
    out = resolve(inc(total=Decimal("150.00")), existing_by_hash=None, candidates=[ex()])
    assert out.branch == "revision"
    assert out.version == 2
    assert out.supersedes_id == "e1"
    assert out.mark_superseded_id == "e1"


def test_revision_within_tolerance_is_duplicate_not_revision():
    # OCR jitter 120.00 -> 120.01 must NOT fabricate a revision (R2)
    out = resolve(inc(total=Decimal("120.01")), existing_by_hash=None, candidates=[ex()])
    assert out.branch == "logical_duplicate"


def test_late_older_version_does_not_supersede_newer(monkeypatch):
    # newer v exists (May 10); an older one (May 1) arrives late -> must NOT
    # supersede the newer; retained as superseded, flagged (R3)
    newer = ex(id="e2", invoice_date=date(2026, 5, 10), total=Decimal("150.00"))
    out = resolve(inc(invoice_date=date(2026, 5, 1), total=Decimal("120.00")),
                  existing_by_hash=None, candidates=[newer])
    assert out.branch == "revision_late"
    assert out.mark_superseded_id is None
    assert out.status_hint == "superseded"
    assert out.needs_review_reason


def test_credit_note_links_to_referenced():
    referenced = ex(id="e1", invoice_number="INV-1", doc_type=DocType.invoice)
    credit = inc(doc_type=DocType.credit_note, invoice_number="CN-9",
                 referenced_invoice_number="INV-1", total=Decimal("-20.00"),
                 file_hash="h-cn")
    out = resolve(credit, existing_by_hash=None, candidates=[referenced])
    assert out.branch == "credit_note"
    assert out.credit_of_id == "e1"
    assert out.status_hint == "credited"


def test_credit_note_orphan_when_reference_missing():
    credit = inc(doc_type=DocType.credit_note, invoice_number="CN-9",
                 referenced_invoice_number="INV-DOES-NOT-EXIST",
                 total=Decimal("-20.00"), file_hash="h-cn")
    out = resolve(credit, existing_by_hash=None, candidates=[])
    assert out.branch == "credit_orphan"
    assert out.credit_of_id is None
    assert out.status_hint == "credited"          # still subtracts from expense
    assert out.needs_review_reason


def test_duplicate_credit_note_not_double_counted():
    # R1: a re-sent (logically identical) credit note must dedup, not create a
    # second credit.
    existing_credit = ex(id="ec1", doc_type=DocType.credit_note,
                         invoice_number="CN-9", total=Decimal("-20.00"))
    credit = inc(doc_type=DocType.credit_note, invoice_number="CN-9",
                 total=Decimal("-20.00"), referenced_invoice_number="INV-1",
                 file_hash="h-cn-2")
    out = resolve(credit, existing_by_hash=None, candidates=[existing_credit])
    assert out.branch == "logical_duplicate"
    assert out.link_to_id == "ec1"


def test_revised_credit_note_supersedes_prior_not_double_counts():
    # Same CN number, changed amount -> must supersede the prior credit, not stack
    # a second one (else the expense is over-reduced).
    existing_credit = ex(id="ec1", doc_type=DocType.credit_note,
                         invoice_number="CN-9", total=Decimal("-20.00"))
    revised = inc(doc_type=DocType.credit_note, invoice_number="CN-9",
                  total=Decimal("-25.00"), referenced_invoice_number="INV-1",
                  file_hash="h-cn-3")
    out = resolve(revised, existing_by_hash=None, candidates=[existing_credit])
    assert out.branch == "revision"
    assert out.supersedes_id == "ec1" and out.mark_superseded_id == "ec1"


def test_no_invoice_number_fuzzy_duplicate():
    # missing number -> fuzzy on (vendor, date, total) (scenario 21 / §6.4)
    out = resolve(inc(invoice_number=None), existing_by_hash=None,
                  candidates=[ex(invoice_number=None)])
    assert out.branch == "logical_duplicate"


def test_brand_new_invoice():
    out = resolve(inc(invoice_number="INV-NEW"), existing_by_hash=None,
                  candidates=[ex(invoice_number="INV-1")])
    assert out.branch == "new"
    assert out.version == 1


def test_revision_targets_latest_active_ignoring_superseded():
    v1 = ex(id="e1", version=1, status="superseded", total=Decimal("100"))
    v2 = ex(id="e2", version=2, status="clean", total=Decimal("120"),
            invoice_date=date(2026, 5, 5))
    out = resolve(inc(total=Decimal("200"), invoice_date=date(2026, 5, 9)),
                  existing_by_hash=None, candidates=[v1, v2])
    assert out.branch == "revision"
    assert out.supersedes_id == "e2"
    assert out.version == 3
