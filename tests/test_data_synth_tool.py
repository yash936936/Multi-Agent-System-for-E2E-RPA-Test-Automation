"""
Regression tests for agents/data_synth/tool.py::generate().

Covers the live bug flagged in the phased debug pass (Phase 4): the cache
is keyed only on test_id, so a spec's data_requirements growing between
runs (e.g. "username" added on a test_id already cached without it) used
to return the stale cached dict verbatim, silently dropping the new
field for every downstream consumer.
"""
from __future__ import annotations

from agents.data_synth.cache import load_cached
from agents.data_synth.tool import generate
from orchestrator.schemas import DataRequirements


def test_generate_fills_missing_field_on_stale_cache(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)

    # First run: only "email" was required, so only "email" got cached.
    first = generate(DataRequirements(fields=["email"], test_id="t-1"))
    assert set(first.values.keys()) == {"email"}

    # Second run: the spec now also requires "username" for the same
    # test_id. The stale cache must not be returned as-is.
    second = generate(DataRequirements(fields=["email", "username"], test_id="t-1"))
    assert "username" in second.values
    # Previously cached value stays stable (TRD §2.4: don't churn already-cached values).
    assert second.values["email"] == first.values["email"]

    # And the fix persists to disk, not just the in-memory return value.
    on_disk = load_cached("t-1")
    assert "username" in on_disk
    assert on_disk["email"] == first.values["email"]


def test_generate_returns_cache_unchanged_when_nothing_missing(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)

    first = generate(DataRequirements(fields=["email", "username"], test_id="t-2"))
    second = generate(DataRequirements(fields=["email", "username"], test_id="t-2"))

    assert second.values == first.values


def test_generate_no_cache_when_test_id_absent(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)

    record = generate(DataRequirements(fields=["email"], test_id=""))
    assert "email" in record.values
    assert list(tmp_path.glob("*.json")) == []
