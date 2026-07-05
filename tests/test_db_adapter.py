from __future__ import annotations

from agents.capability.db_adapter import DbAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


def _run(query: str, connection_string: str = "sqlite:///:memory:", expected: dict | None = None):
    adapter = DbAdapter()
    return adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.DATABASE,
            target="",
            params={"connection_string": connection_string, "query": query},
            expected=expected or {},
        )
    )


def test_select_query_still_works():
    result = _run("SELECT 1 as one", expected={"row_count": 1})
    assert result.passed is True
    assert result.evidence["row_count"] == 1


def test_with_cte_query_still_works():
    result = _run("WITH x AS (SELECT 1 as v) SELECT * FROM x")
    assert result.passed is True


def test_drop_table_is_refused():
    result = _run("DROP TABLE users")
    assert result.passed is False
    assert "read-only" in result.evidence["error"].lower()


def test_delete_is_refused():
    result = _run("DELETE FROM users WHERE 1=1")
    assert result.passed is False


def test_update_is_refused():
    result = _run("UPDATE users SET role='admin' WHERE username='attacker'")
    assert result.passed is False


def test_insert_is_refused():
    result = _run("INSERT INTO users (username, role) VALUES ('x', 'admin')")
    assert result.passed is False


def test_stacked_statement_smuggling_is_rejected_by_the_driver():
    # A SELECT prefix alone wouldn't stop a stacked "SELECT 1; DROP
    # TABLE ..." -- but SQLAlchemy's default execute() doesn't support
    # multiple statements per call at all, so this fails safely with a
    # driver-level error before the DROP ever runs. Documented here so
    # this protection isn't accidentally assumed to come from the
    # allowlist above if the driver/execution style ever changes.
    result = _run("SELECT 1; DROP TABLE users;--")
    assert result.passed is False


def test_missing_query_still_fails_clearly():
    result = _run("")
    assert result.passed is False
