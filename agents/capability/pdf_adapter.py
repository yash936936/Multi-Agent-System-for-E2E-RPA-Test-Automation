from pypdf import PdfReader
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class PdfAdapter:
    """
    Phase 15: Validates PDF documents (Read-Only).
    Phase 16b: Adds real OCR for scanned/image-only PDFs. The engine
    (pytesseract) was already a project dependency, wired to the Vision
    Core screenshot pipeline but never connected here -- this closes
    that gap. pypdf's extract_text() returns nothing for scanned pages
    (there's no text layer), so `text_contains` checks now fall back to
    rasterizing each page (via pymupdf, no poppler system dependency)
    and running pytesseract against it whenever the native text layer
    is empty, or whenever the caller explicitly sets force_ocr=True.
    """
    capability_type: CapabilityType = CapabilityType.PDF_OCR

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        file_path = params.get("file_path")
        force_ocr = params.get("force_ocr", False)
        ocr_dpi = params.get("ocr_dpi", 200)

        if not file_path:
            return self._fail("Missing 'file_path'")

        try:
            reader = PdfReader(file_path)
            evidence = {
                "page_count": len(reader.pages),
                "is_encrypted": reader.is_encrypted
            }
            passed = True

            if expected.get("page_count") is not None:
                if evidence["page_count"] != expected["page_count"]:
                    passed = False
                    evidence["page_count_mismatch"] = True

            if expected.get("metadata"):
                doc_meta = reader.metadata or {}
                meta_mismatches = {}
                for k, v in expected["metadata"].items():
                    actual = doc_meta.get(k) or doc_meta.get(f"/{k}")
                    if actual != v:
                        passed = False
                        meta_mismatches[k] = {"expected": v, "actual": str(actual)}
                if meta_mismatches:
                    evidence["metadata_mismatches"] = meta_mismatches

            if expected.get("text_contains"):
                search_terms = expected["text_contains"]
                if isinstance(search_terms, str):
                    search_terms = [search_terms]

                full_text = ""
                for page in reader.pages:
                    full_text += page.extract_text() or ""

                used_ocr = False
                if force_ocr or not full_text.strip():
                    # No (usable) native text layer -- this is very
                    # likely a scanned/image-only PDF. Rasterize and OCR
                    # it instead of silently reporting "missing" text
                    # that was never extractable in the first place.
                    full_text = self._ocr_extract(file_path, ocr_dpi)
                    used_ocr = True
                    evidence["ocr_used"] = True

                missing_terms = [term for term in search_terms if term not in full_text]
                if missing_terms:
                    passed = False
                    evidence["missing_text_terms"] = missing_terms
                if used_ocr:
                    evidence["ocr_extracted_char_count"] = len(full_text)

            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed,
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        except Exception as e:
            return self._fail(f"PDF processing error: {str(e)}")

    @staticmethod
    def _ocr_extract(file_path: str, dpi: int) -> str:
        """
        Rasterizes every page via PyMuPDF (no poppler/pdf2image system
        dependency needed) and runs pytesseract against each page image,
        concatenating the results. Deferred imports so importing this
        module doesn't require Tesseract to be installed unless a scan
        actually needs OCR.
        """
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io

        text_parts = []
        doc = fitz.open(file_path)
        try:
            zoom = dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            for page in doc:
                pix = page.get_pixmap(matrix=matrix)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                text_parts.append(pytesseract.image_to_string(image))
        finally:
            doc.close()
        return "\n".join(text_parts)

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False
        )
