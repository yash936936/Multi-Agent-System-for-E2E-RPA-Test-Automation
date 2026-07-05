"""
Regression test for the reported bug:

    ImportError: cannot import name 'RunMemoryStore' from 'orchestrator.memory'

Root cause: orchestrator/memory.py (a module) and orchestrator/memory/ (a
directory used only for state.db/api_runs.db storage) both existed side
by side. Python's FileFinder resolves a module-vs-package name collision
based on filesystem directory-entry order, which differs across OSes --
so `from orchestrator.memory import RunMemoryStore` could succeed on one
machine and fail on another (this is exactly what happened: it worked in
CI/Linux but crashed for the reporting user on Windows).

Fix: the data directory was renamed to orchestrator/memory_store/ so it
no longer shares a name with orchestrator/memory.py. This test guards
against the collision being reintroduced.
"""
from __future__ import annotations

from pathlib import Path

from config.settings import settings


def test_memory_dir_does_not_collide_with_memory_module():
    project_root = Path(__file__).resolve().parent.parent
    memory_module = project_root / "orchestrator" / "memory.py"
    assert memory_module.is_file()

    # The directory settings.memory_dir points at must NOT be named
    # "memory" -- that would recreate the module/package collision.
    assert settings.memory_dir.name != "memory"

    # And a literal orchestrator/memory/ directory must not exist at all,
    # regardless of what settings.memory_dir is configured to.
    literal_memory_dir = project_root / "orchestrator" / "memory"
    assert not literal_memory_dir.is_dir()


def test_run_memory_store_importable():
    # The actual regression: this import must always succeed.
    from orchestrator.memory import RunMemoryStore  # noqa: F401
