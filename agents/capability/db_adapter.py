import re

import sqlalchemy
from sqlalchemy.exc import SQLAlchemyError
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

# This adapter's entire purpose (per its own docstring, and per the "assert
# things are true about a system" role every other capability adapter
# plays) is read-only validation. Previously nothing enforced that: a
# `query` param was executed verbatim via sqlalchemy.text(), so any
# authenticated user able to submit a guided-mode spec (role=executor is
# enough -- not just admin) could run DROP/DELETE/UPDATE/INSERT against
# whatever connection_string they supplied, using AURA's own server-side
# network access as the vector. This is a statement-type allowlist, not a
# perfect SQL sandbox (a SELECT can still invoke a mutating stored
# function in some engines) -- but it closes the obvious, direct
# arbitrary-write path while allowing every real read-only assertion this
# adapter is meant to support.
_READ_ONLY_PREFIX = re.compile(r"^\s*(?:\()*\s*(SELECT|WITH|EXPLAIN|SHOW|PRAGMA|DESC|DESCRIBE)\b", re.IGNORECASE)

# 2026-07-13 (decisions.md D-017 / roadmap issue 1.7): the prefix allowlist
# above only rejects statements that don't *start* with a read verb -- it
# says nothing about mutating or file/process side effects hidden inside an
# otherwise-syntactically-valid SELECT, e.g.:
#   SELECT setval('users_id_seq', 1)             -- Postgres: mutates a sequence
#   SELECT pg_terminate_backend(123)              -- Postgres: kills another session
#   SELECT lo_export(loid, '/tmp/x')              -- Postgres: writes a file to disk
#   SELECT * FROM OPENROWSET(...)                 -- SQL Server: arbitrary data source
#   SELECT LOAD_FILE('/etc/passwd')               -- MySQL: reads a file
#   SELECT ... INTO OUTFILE '/tmp/x'              -- MySQL: writes a file
# This is a second, cheap gate: reject queries containing known
# mutating/exfiltration function or clause names, checked anywhere in the
# query text (not just the prefix). It is still a **denylist of known
# dangerous patterns, not a real SQL parser or sandbox** -- a sufficiently
# creative dialect-specific construct not on this list could still get
# through. This does not claim to be a complete SQL injection defense; it
# closes the specific, named gap the roadmap flagged. If stronger
# guarantees are ever needed, the real fix is running these queries
# against a connection whose DB-level grants are read-only, which is an
# operator/deployment concern this adapter cannot enforce from inside
# Python regardless of how sophisticated the pattern list gets.
_MUTATING_FUNCTION_PATTERNS = re.compile(
    r"\b("
    r"EXEC(?:UTE)?|CALL|xp_cmdshell|sp_executesql|OPENROWSET|OPENQUERY|"
    r"LOAD_FILE|INTO\s+OUTFILE|INTO\s+DUMPFILE|"
    r"setval|nextval|lo_import|lo_export|lo_put|pg_terminate_backend|"
    r"pg_read_file|pg_ls_dir|dblink(?:_exec)?"
    r")\s*\(|"
    r"\b(EXEC(?:UTE)?|CALL|INTO\s+OUTFILE|INTO\s+DUMPFILE)\b",
    re.IGNORECASE,
)


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

        if not _READ_ONLY_PREFIX.match(query):
            return self._fail(
                "Refusing to run a non-read-only query. DbAdapter only validates "
                "state (SELECT/WITH/EXPLAIN/SHOW/PRAGMA/DESCRIBE) -- it does not "
                "execute DDL/DML (INSERT/UPDATE/DELETE/DROP/etc.)."
            )

        mutating_match = _MUTATING_FUNCTION_PATTERNS.search(query)
        if mutating_match:
            return self._fail(
                f"Refusing to run a query containing '{mutating_match.group(0).strip()}' -- "
                "this looks like a mutating, file-access, or session-control function/clause "
                "hidden inside an otherwise read-only statement. DbAdapter is detect-only; "
                "see agents/capability/db_adapter.py for the full denylist and its documented "
                "limits (this is a pattern denylist, not a full SQL sandbox)."
            )
            
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
                        "error_type": error_type,
                        # 2026-07-13 (decisions.md D-017 / roadmap issue 1.6):
                        # cross_modal_diagnoser.py::_heal_db_drift() reads
                        # hints.get("exception", ...) to regex-match
                        # "column X does not exist" errors -- but this key
                        # was never actually populated here, only at the
                        # top-level evidence dict (one level up from
                        # `healing_hints`, which is what the diagnoser
                        # receives). The column-drift detection path could
                        # therefore never fire; it always matched against
                        # an empty string. Duplicating error_msg here (not
                        # renaming/moving it -- other evidence consumers
                        # may already read evidence["exception"]) fixes the
                        # actual data flow without changing either
                        # consumer's existing interface.
                        "exception": error_msg,
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