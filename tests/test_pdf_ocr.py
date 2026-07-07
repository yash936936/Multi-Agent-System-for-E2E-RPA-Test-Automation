from types import SimpleNamespace

from agents.capability.pdf_adapter import PdfAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


def _fake_pdf_reader(native_text: str = ""):
    page = SimpleNamespace(extract_text=lambda: native_text)
    return SimpleNamespace(pages=[page], metadata={}, is_encrypted=False)


def test_pdf_adapter_ocr_extracts_text_from_scanned_pdf(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scanned.pdf"
    adapter = PdfAdapter()
    monkeypatch.setattr("agents.capability.pdf_adapter.PdfReader", lambda file_path: _fake_pdf_reader())
    monkeypatch.setattr(adapter, "_ocr_extract", lambda file_path, dpi: "AURA VERIFIED")
    payload = CapabilityCheckInput(
        capability=CapabilityType.PDF_OCR, target=str(pdf_path),
        params={"file_path": str(pdf_path)},
        expected={"text_contains": "AURA"},
    )
    result = adapter.run(payload)
    assert result.evidence.get("ocr_used") is True
    assert result.passed is True, result.evidence


def test_pdf_adapter_native_text_layer_skips_ocr(tmp_path, monkeypatch):
    pdf_path = tmp_path / "native.pdf"
    adapter = PdfAdapter()
    monkeypatch.setattr(
        "agents.capability.pdf_adapter.PdfReader",
        lambda file_path: _fake_pdf_reader("Native text layer present"),
    )
    monkeypatch.setattr(
        adapter,
        "_ocr_extract",
        lambda file_path, dpi: (_ for _ in ()).throw(AssertionError("OCR should not be called")),
    )
    payload = CapabilityCheckInput(
        capability=CapabilityType.PDF_OCR, target=str(pdf_path),
        params={"file_path": str(pdf_path)},
        expected={"text_contains": "Native text layer"},
    )
    result = adapter.run(payload)
    assert result.passed is True
    assert "ocr_used" not in result.evidence
