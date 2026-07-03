import sqlalchemy
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class DbAdapter:
    """
    Phase 14: Validates database state post-action (Read-Only).
    Params: connection_string, query
    Expected: row_count (int), values (dict of col:val for the first row)
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
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=1.0,
                evidence={"error": "Missing 'connection_string' or 'query'"}, escalate=False
            )
            
        try:
            engine = sqlalchemy.create_engine(connection_string)
            with engine.connect() as conn:
                # SQLAlchemy 2.0 requires text() for raw SQL strings
                result = conn.execute(sqlalchemy.text(query))
                rows = result.fetchall()
                columns = result.keys()
                
            passed = True
            evidence = {"row_count": len(rows), "columns": list(columns)}
            
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
        except Exception as e:
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=0.0,
                evidence={"exception": str(e)}, escalate=False
            )