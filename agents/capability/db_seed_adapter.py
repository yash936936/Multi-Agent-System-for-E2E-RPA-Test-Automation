"""
Database seeding adapter — agents/capability/db_seed_adapter.py

Roadmap Phase O (docs/Roadmap.md §10, decisions.md D-036). AURA's
first-ever *intentional write path* to a database, given its own phase
(and its own file) rather than folded into db_adapter.py, on purpose:
db_adapter.py's entire reason for existing is read-only state validation
(see its own module docstring / decisions.md D-017's mutating-pattern
hardening); loosening it to also write would undermine every guarantee
that file makes. This is a **new, separate, additive capability**
(`CapabilityType.DB_SEED`) — db_adapter.py is untouched by this phase and
stays exactly as strict as it was before.

Design constraints, each load-bearing (not just style preferences):

1. **Structured input only, never raw SQL text.** Params describe a
   `table` name plus either a `values` dict (single row) or a `rows` list
   of dicts (batch), never a query string. This adapter builds the
   parameterized INSERT itself. A free-text query param would reopen
   exactly the injection surface db_adapter.py's own hardening (D-017)
   exists to close — there is no "seed adapter" version of that mistake
   available to make, because there is no query-string param to accept in
   the first place.
2. **Only INSERT.** No UPDATE/DELETE/DDL, structured or otherwise.
   Precondition seeding means creating rows that didn't exist, not
   mutating or erasing existing ones. This isn't a runtime check against
   a denylist (there's nothing to deny — the adapter only ever emits one
   statement shape); it's a structural guarantee from what this code is
   capable of building.
3. **Explicit, separate opt-in.** `settings.allow_db_seeding` (default
   `False`) gates this adapter independently of the general
   `capability_adapters_enabled` kill switch enforced upstream in
   `orchestrator/capability_router.py`. That switch answers "is outbound
   capability-adapter traffic allowed at all"; this one answers "is
   *writing* to a database specifically allowed" — a deliberately separate
   question, checked here (inside the adapter) rather than folded into the
   router's generic gate, since it is specific to this one adapter and
   should stay that way rather than growing into a per-adapter special
   case inside a file meant to stay adapter-agnostic.
4. **Every seed operation is audited.** Reuses the existing
   `orchestrator/audit_logger.py` singleton (the same sink
   `capability_router.py` already writes `CAPABILITY_EGRESS` records to),
   with a new `DB_SEED` action recording the target table and the exact
   rows written — deliberately more detail than the router's own
   host-only egress log, since this is the one adapter in the whole
   capability layer that leaves the database in a different state than it
   found it, and is the adapter "most worth having a paper trail for"
   per the roadmap's own framing.

Table and column identifiers are interpolated into the SQL text (SQL does
not support parameter binding for identifiers), so they are validated
against a strict `^[A-Za-z_][A-Za-z0-9_]*$` allowlist pattern before use —
anything else is rejected outright rather than escaped/quoted, since a
quoting-based defense for identifiers is exactly the kind of "clever
escaping" corner db_adapter.py's own denylist commentary (D-017) warns
against relying on. Only the *values* go through real parameter binding
(`sqlalchemy.text(...)` with bound `:paramN` placeholders), which is the
part SQL actually lets you bind safely.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import sqlalchemy
from sqlalchemy.exc import SQLAlchemyError

from config.settings import settings
from orchestrator.audit_logger import audit_logger
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DbSeedAdapter:
    """
    Phase O: Seeds database precondition state via structured, parameterized
    INSERT statements only. Off by default (settings.allow_db_seeding).
    """

    capability_type: CapabilityType = CapabilityType.DB_SEED

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params or {}

        # Second, deliberate gate -- independent of the router's general
        # capability_adapters_enabled kill switch. Checked first, before
        # even validating the rest of params, so a disabled deployment
        # gets a clean, uniform rejection regardless of what else is wrong
        # with the call.
        if not settings.allow_db_seeding:
            return self._fail(
                "Database seeding is disabled (settings.allow_db_seeding is False). "
                "This is a separate, explicit opt-in from capability_adapters_enabled -- "
                "set AURA_ALLOW_DB_SEEDING=true (or settings.allow_db_seeding = True) "
                "to enable the one capability adapter that writes."
            )

        connection_string = params.get("connection_string")
        table = params.get("table")
        rows = self._normalize_rows(params)

        if not connection_string:
            return self._fail("Missing 'connection_string'")
        if not table:
            return self._fail("Missing 'table'")
        if not _IDENTIFIER.match(table):
            return self._fail(
                f"Invalid table name '{table}' -- must match ^[A-Za-z_][A-Za-z0-9_]*$ "
                "(quoted/schema-qualified/special-character table names are not supported "
                "by this adapter's identifier allowlist, by design)."
            )
        if rows is None:
            return self._fail("Missing 'values' (single row dict) or 'rows' (list of row dicts)")
        if not rows:
            return self._fail("'rows' was an empty list -- nothing to seed")

        # Every row must share the same column set, so one parameterized
        # INSERT statement (with a fixed column list) covers the whole
        # batch. Divergent column sets across rows in one call is a caller
        # error, not something this adapter silently papers over by
        # running a different statement per row.
        columns = list(rows[0].keys())
        for row in rows:
            if list(row.keys()) != columns:
                return self._fail(
                    "All rows in a single seed call must have the same columns, in the same "
                    "order -- got mismatched column sets across 'rows'. Issue separate calls "
                    "for rows with different shapes."
                )
        for col in columns:
            if not _IDENTIFIER.match(col):
                return self._fail(
                    f"Invalid column name '{col}' -- must match ^[A-Za-z_][A-Za-z0-9_]*$"
                )
        if not columns:
            return self._fail("Row(s) had no columns -- nothing to insert")

        col_list = ", ".join(columns)
        placeholder_list = ", ".join(f":{c}" for c in columns)
        insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholder_list})"

        try:
            engine = sqlalchemy.create_engine(connection_string)
            with engine.begin() as conn:
                for row in rows:
                    conn.execute(sqlalchemy.text(insert_sql), row)
        except SQLAlchemyError as e:
            raw_error = str(e)
            orig = getattr(e, "orig", None)
            while orig is not None and hasattr(orig, "orig"):
                orig = orig.orig
            error_msg = str(orig) if orig is not None else raw_error
            error_type = type(orig).__name__ if orig is not None else "UnknownSQLAlchemyError"
            return CapabilityCheckResult(
                capability=self.capability_type,
                passed=False,
                confidence=0.0,
                evidence={
                    "exception": error_msg,
                    "error_type": error_type,
                    "table": table,
                    "attempted_row_count": len(rows),
                },
                escalate=True,
            )
        except Exception as e:
            return self._fail(f"DB seed execution error: {str(e)}")

        # Audit every seed operation, including the exact rows written --
        # this adapter is the one most worth having a paper trail for.
        audit_logger.log(
            tenant_id="system",
            user_id="system",
            action="DB_SEED",
            resource=table,
            details={"table": table, "row_count": len(rows), "rows": rows},
        )

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=True,
            confidence=1.0,
            evidence={"table": table, "row_count": len(rows), "columns": columns, "rows": rows},
            escalate=False,
        )

    @staticmethod
    def _normalize_rows(params: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Accepts either a single-row `values` dict or a multi-row `rows`
        list of dicts (not both -- `rows` wins if somehow both are
        supplied, since it's the more general form). Returns None if
        neither was supplied at all, so the caller can distinguish
        "nothing given" from "given but empty".
        """
        rows = params.get("rows")
        if rows is not None:
            if not isinstance(rows, list):
                return None
            return rows
        values = params.get("values")
        if values is not None:
            if not isinstance(values, dict):
                return None
            return [values]
        return None

    def _fail(self, msg: str) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=True,
        )
