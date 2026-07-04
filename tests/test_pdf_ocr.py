import io

import fitz
from PIL import Image, ImageDraw, ImageFont

from agents.capability.pdf_adapter import PdfAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


def _make_scanned_pdf(path: str, text: str) -> None:
    """
    Builds a PDF with zero text layer -- just a page-sized image of
    rendered text -- to stand in for a real scanned document. Uses
    PyMuPDF only (no poppler / external binaries), matching the
    dependency the adapter itself uses.
    """
    image = Image.new("RGB", (800, 300), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 48)
    except Exception:
        font = ImageFont.load_default()
    draw.text((40, 100), text, fill="black", font=font)

    buf = io.BytesIO()
    image.save(buf, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=800, height=300)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


def test_pdf_adapter_ocr_extracts_text_from_scanned_pdf(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _make_scanned_pdf(str(pdf_path), "AURA VERIFIED")

    adapter = PdfAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.PDF_OCR, target=str(pdf_path),
        params={"file_path": str(pdf_path)},
        expected={"text_contains": "AURA"},
    )
    result = adapter.run(payload)
    assert result.evidence.get("ocr_used") is True
    assert result.passed is True, result.evidence


def test_pdf_adapter_native_text_layer_skips_ocr(tmp_path):
    # A PDF with a real text layer should not trigger OCR at all.
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Native text layer present")
    pdf_path = tmp_path / "native.pdf"
    doc.save(str(pdf_path))
    doc.close()

    adapter = PdfAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.PDF_OCR, target=str(pdf_path),
        params={"file_path": str(pdf_path)},
        expected={"text_contains": "Native text layer"},
    )
    result = adapter.run(payload)
    assert result.passed is True
    assert "ocr_used" not in result.evidence
