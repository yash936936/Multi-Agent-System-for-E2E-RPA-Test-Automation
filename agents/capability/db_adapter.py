import sqlalchemy
from sqlalchemy.exc import SQLAlchemyError
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class DbAdapter:
    """
    Phase 18: Validates database state (Read-Only) with Cross-Modal Healing support.
    """
    capability_type: CapabilityType = CapabilityType.DATABASE

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        
        connection_string = params.get("connection_string")
        query = params.get("query")
        expected_row_count = expected.get("row_count")
        expected_values = expected.get("values")
        
        if not connection_string or not query:
            return self._fail("Missing 'connection_string' or 'query'")
            
        try:
            engine = sqlalchemy.create_engine(connection_string)
            with engine.connect() as conn:
                result = conn.execute(sqlalchemy.text(query))
                
                # Safe extraction of columns
                columns = list(result.keys()) if result.returns_rows else []
                rows = result.fetchall() if result.returns_rows else []
                
            passed = True
            evidence = {"row_count": len(rows), "columns": columns}
            
            if expected_row_count is not None and len(rows) != expected_row_count:
                passed = False
                evidence["expected_row_count_mismatch"] = True
                
            if expected_values and rows:
                row_dict = dict(zip(columns, rows[0]))
                for k, v in expected_values.items():
                    if row_dict.get(k) != v:
                        passed = False
                        evidence[f"value_mismatch_{k}"] = f"Expected {v}, got {row_dict.get(k)}"
                        
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.5, evidence=evidence, escalate=False
            )
            
        except SQLAlchemyError as e:
            # Debug Fix: Safe iterative unwrap of SQLAlchemy exception chains
            raw_error = str(e)
            orig = getattr(e, 'orig', None)
            while orig is not None and hasattr(orig, 'orig'):
                orig = orig.orig
                
            error_msg = str(orig) if orig is not None else raw_error
            error_type = type(orig).__name__ if orig is not None else "UnknownSQLAlchemyError"
            
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=0.0,
                evidence={
                    "exception": error_msg,
                    "healing_hints": {
                        "query_failed": query,
                        "error_type": error_type
                    }
                }, escalate=False
            )
        except Exception as e:
            return self._fail(f"DB execution error: {str(e)}")

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False
        )