from pypdf import PdfReader
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class PdfAdapter:
    """
    Phase 15: Validates PDF documents (Read-Only).
    """
    capability_type: CapabilityType = CapabilityType.PDF_OCR

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        file_path = params.get("file_path")
        
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
                # Debug Fix: Fallback to empty dict if metadata is None
                doc_meta = reader.metadata or {}
                meta_mismatches = {}
                for k, v in expected["metadata"].items():
                    # pypdf metadata keys often have leading '/' or specific formatting
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
                    
                missing_terms = [term for term in search_terms if term not in full_text]
                if missing_terms:
                    passed = False
                    evidence["missing_text_terms"] = missing_terms
                    
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        except Exception as e:
            return self._fail(f"PDF processing error: {str(e)}")

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False
        )