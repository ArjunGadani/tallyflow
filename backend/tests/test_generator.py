"""The generator must produce every §2 hard case as real, well-formed files that
route correctly (digital->text, image->vision, corrupt->unreadable)."""
import io

from PIL import Image

from backend.preprocess import detect_pdf_page_types, pdf_page_count
from generator.generate import generate_all


def test_generates_all_scenarios(tmp_path):
    m = generate_all(str(tmp_path))
    scenarios = {i["scenario"] for i in m.items}
    for required in {"clean_digital", "exact_duplicate", "logical_duplicate", "revision",
                     "credit_note", "multi_invoice", "non_invoice", "totals_mismatch",
                     "ambiguous_date", "foreign_currency", "multi_tax", "scanned_image",
                     "corrupt"}:
        assert required in scenarios, f"missing scenario: {required}"
    assert (tmp_path / "manifest.json").exists()


def test_exact_duplicate_is_byte_identical(tmp_path):
    generate_all(str(tmp_path))
    a = (tmp_path / "01_clean_invoice.pdf").read_bytes()
    b = (tmp_path / "02_exact_duplicate.pdf").read_bytes()
    assert a == b                       # same hash -> exact-duplicate path


def test_digital_pdf_routes_to_text(tmp_path):
    generate_all(str(tmp_path))
    data = (tmp_path / "01_clean_invoice.pdf").read_bytes()
    assert detect_pdf_page_types(data) == ["digital"]


def test_multi_invoice_has_two_pages(tmp_path):
    generate_all(str(tmp_path))
    assert pdf_page_count((tmp_path / "06_multi_invoice.pdf").read_bytes()) == 2


def test_scanned_image_is_a_valid_image(tmp_path):
    generate_all(str(tmp_path))
    img = Image.open(io.BytesIO((tmp_path / "12_scanned_invoice.png").read_bytes()))
    assert img.size[0] > 100
