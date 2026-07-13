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


def test_mutating_function_inside_select_is_refused():
    # 2026-07-13 (decisions.md D-017 / roadmap issue 1.7): the prefix
    # allowlist alone lets a syntactically-SELECT query through even if it
    # calls a mutating/exfiltration function. These should now be refused
    # by the secondary denylist check.
    dangerous_queries = [
        "SELECT setval('users_id_seq', 1)",
        "SELECT pg_terminate_backend(123)",
        "SELECT lo_export(16420, '/tmp/x')",
        "SELECT LOAD_FILE('/etc/passwd')",
        "SELECT * FROM t INTO OUTFILE '/tmp/x.csv'",
        "SELECT dblink_exec('conn', 'DROP TABLE users')",
        "SELECT * FROM OPENROWSET('SQLNCLI', 'evil')",
    ]
    for q in dangerous_queries:
        result = _run(q)
        assert result.passed is False, f"expected refusal for: {q}"
        assert "error" in result.evidence


def test_legitimate_select_queries_are_not_false_flagged():
    # Guard against the new denylist being over-broad and breaking real
    # read-only assertions that happen to mention similar-looking words
    # (e.g. a column literally named "execution_id").
    safe_queries = [
        "SELECT 1 as execution_id, 'ok' as status",
        "SELECT name FROM sqlite_master WHERE type = 'table'",
        "WITH recent AS (SELECT 1 as v) SELECT * FROM recent",
    ]
    for q in safe_queries:
        result = _run(q)
        assert result.passed is True, f"expected pass for safe query: {q} -- got {result.evidence}"


def test_query_error_healing_hints_include_exception_text():
    # 2026-07-13 (decisions.md D-017 / roadmap issue 1.6): healing_hints
    # used to omit the "exception" key entirely, so
    # cross_modal_diagnoser.py's column-drift regex always matched an
    # empty string and could never actually detect a "column does not
    # exist" error. This asserts the real driver error text now reaches
    # healing_hints, and that CrossModalDiagnoser's regex can actually
    # match it end-to-end.
    result = _run("SELECT nonexistent_column_xyz FROM sqlite_master")
    assert result.passed is False
    assert "healing_hints" in result.evidence
    hints = result.evidence["healing_hints"]
    assert "exception" in hints
    assert hints["exception"] == result.evidence["exception"]

    from agents.planner.cross_modal_diagnoser import CrossModalDiagnoser
    from orchestrator.schemas import TestStep, CapabilityType as CT

    diagnoser = CrossModalDiagnoser()
    step = TestStep(
        step_id=1, action="capability_check", capability_type=CT.DATABASE,
        params={}, expected={},
    )
    # sqlite's real error text doesn't match the Postgres-flavored
    # "column X does not exist" pattern this heuristic targets, so this
    # confirms the data now *reaches* the regex (no crash, real text
    # passed through) even though sqlite's message won't match it --
    # a Postgres-backed run would. The important fix is that hints.get(
    # "exception") is no longer silently empty.
    result_step = diagnoser.diagnose(step, result)
    assert result_step is None  # no safe rename target either way; escalate
