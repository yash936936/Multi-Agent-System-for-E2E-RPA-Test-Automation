"""
Phase O tests — agents/capability/db_seed_adapter.py

Covers: the settings.allow_db_seeding gate, structured single-row and
multi-row (batch) INSERT, identifier validation for table/column names,
mismatched-row-shape rejection, audit logging of exact rows written, and
that only INSERT is ever possible (no query-string param exists to smuggle
UPDATE/DELETE/DDL through).

See docs/Roadmap.md §10 (Phase O) and docs/decisions.md D-036.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
import sqlalchemy

from agents.capability.db_seed_adapter import DbSeedAdapter
from config.settings import settings
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


@pytest.fixture
def seeding_enabled():
    original = settings.allow_db_seeding
    settings.allow_db_seeding = True
    yield
    settings.allow_db_seeding = original


@pytest.fixture
def sqlite_db(tmp_path):
    db_path = tmp_path / "seed_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"


def _run(connection_string, table=None, values=None, rows=None, capability_params_extra=None):
    adapter = DbSeedAdapter()
    params = {"connection_string": connection_string}
    if table is not None:
        params["table"] = table
    if values is not None:
        params["values"] = values
    if rows is not None:
        params["rows"] = rows
    if capability_params_extra:
        params.update(capability_params_extra)
    return adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.DB_SEED,
            target="",
            params=params,
            expected={},
        )
    )


def _select_all(connection_string, table):
    engine = sqlalchemy.create_engine(connection_string)
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(f"SELECT * FROM {table}"))
        return [dict(zip(result.keys(), row)) for row in result.fetchall()]


# --- Gate ---

def test_disabled_by_default_refuses_even_with_valid_params(sqlite_db):
    assert settings.allow_db_seeding is False
    result = _run(sqlite_db, table="users", values={"id": 1, "username": "alice", "role": "admin"})
    assert result.passed is False
    assert "allow_db_seeding" in result.evidence["error"]
    # Confirm nothing was actually written.
    assert _select_all(sqlite_db, "users") == []


def test_enabled_allows_seeding(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="users", values={"id": 1, "username": "alice", "role": "admin"})
    assert result.passed is True
    rows = _select_all(sqlite_db, "users")
    assert rows == [{"id": 1, "username": "alice", "role": "admin"}]


# --- Single row / batch rows ---

def test_single_row_via_values(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="users", values={"id": 1, "username": "bob", "role": "user"})
    assert result.passed is True
    assert result.evidence["row_count"] == 1


def test_batch_rows(seeding_enabled, sqlite_db):
    result = _run(
        sqlite_db,
        table="users",
        rows=[
            {"id": 1, "username": "alice", "role": "admin"},
            {"id": 2, "username": "bob", "role": "user"},
        ],
    )
    assert result.passed is True
    assert result.evidence["row_count"] == 2
    rows = _select_all(sqlite_db, "users")
    assert len(rows) == 2


def test_mismatched_row_shapes_rejected(seeding_enabled, sqlite_db):
    result = _run(
        sqlite_db,
        table="users",
        rows=[
            {"id": 1, "username": "alice", "role": "admin"},
            {"id": 2, "username": "bob"},  # missing 'role'
        ],
    )
    assert result.passed is False
    assert "same columns" in result.evidence["error"]
    assert _select_all(sqlite_db, "users") == []


def test_empty_rows_list_rejected(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="users", rows=[])
    assert result.passed is False
    assert "empty" in result.evidence["error"].lower()


def test_missing_values_and_rows_rejected(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="users")
    assert result.passed is False
    assert "values" in result.evidence["error"] or "rows" in result.evidence["error"]


# --- Identifier validation (table/column names are interpolated, not bound) ---

def test_invalid_table_name_rejected(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="users; DROP TABLE users; --", values={"id": 1})
    assert result.passed is False
    assert "table name" in result.evidence["error"].lower()


def test_invalid_column_name_rejected(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="users", values={"id; DROP TABLE users; --": 1})
    assert result.passed is False
    assert "column name" in result.evidence["error"].lower()


def test_valid_snake_case_identifiers_pass(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="users", values={"id": 3, "username": "carol", "role": "admin"})
    assert result.passed is True


# --- Only INSERT is possible: there's no query-string param to abuse ---

def test_no_query_param_accepted_at_all(seeding_enabled, sqlite_db):
    """Even if a caller tries to sneak a 'query' param in (as if this were
    db_adapter.py), it's simply ignored -- there is no code path in this
    adapter that reads or executes arbitrary SQL text."""
    result = _run(
        sqlite_db,
        table="users",
        values={"id": 1, "username": "x", "role": "y"},
        capability_params_extra={"query": "DROP TABLE users"},
    )
    assert result.passed is True
    # Table still exists and has exactly the one seeded row -- the
    # smuggled 'query' param had no effect.
    assert len(_select_all(sqlite_db, "users")) == 1


# --- Audit logging ---

def test_seed_operation_is_audited_with_exact_rows(seeding_enabled, sqlite_db):
    with patch("agents.capability.db_seed_adapter.audit_logger") as mock_audit:
        result = _run(
            sqlite_db,
            table="users",
            rows=[{"id": 1, "username": "alice", "role": "admin"}],
        )
    assert result.passed is True
    mock_audit.log.assert_called_once()
    _, kwargs = mock_audit.log.call_args
    assert kwargs["action"] == "DB_SEED"
    assert kwargs["resource"] == "users"
    assert kwargs["details"]["rows"] == [{"id": 1, "username": "alice", "role": "admin"}]
    assert kwargs["details"]["row_count"] == 1


def test_failed_seed_is_not_audited(seeding_enabled, sqlite_db):
    with patch("agents.capability.db_seed_adapter.audit_logger") as mock_audit:
        result = _run(sqlite_db, table="users", rows=[])
    assert result.passed is False
    mock_audit.log.assert_not_called()


# --- DB-level failure surfaces cleanly (e.g. table doesn't exist) ---

def test_nonexistent_table_fails_cleanly(seeding_enabled, sqlite_db):
    result = _run(sqlite_db, table="does_not_exist", values={"id": 1})
    assert result.passed is False
    assert result.escalate is True
    assert "exception" in result.evidence
