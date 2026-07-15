from __future__ import annotations

from config.settings import Settings, _resolve_env_files


def test_resolve_env_files_no_profile_returns_base_only(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings._PROJECT_ENV_FILE", tmp_path / ".env")
    files = _resolve_env_files(None)
    assert files == (tmp_path / ".env",)


def test_resolve_env_files_missing_profile_file_falls_back_to_base_only(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings._PROJECT_ENV_FILE", tmp_path / ".env")
    files = _resolve_env_files("nonexistent_profile")
    assert files == (tmp_path / ".env",)


def test_resolve_env_files_existing_profile_appends_it(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings._PROJECT_ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env.staging").write_text("AURA_COMPRESSION_MODE=balanced\n")
    files = _resolve_env_files("staging")
    assert files == (tmp_path / ".env", tmp_path / ".env.staging")


def test_profile_env_file_overrides_base_env_file(tmp_path):
    (tmp_path / ".env").write_text("AURA_COMPRESSION_MODE=max\n")
    (tmp_path / ".env.staging").write_text("AURA_COMPRESSION_MODE=balanced\n")

    s = Settings(project_root=tmp_path, _env_file=(tmp_path / ".env", tmp_path / ".env.staging"))
    assert s.compression_mode == "balanced"


def test_base_only_when_profile_file_absent(tmp_path):
    (tmp_path / ".env").write_text("AURA_COMPRESSION_MODE=off\n")

    s = Settings(project_root=tmp_path, _env_file=(tmp_path / ".env",))
    assert s.compression_mode == "off"


def test_reload_profile_mutates_in_place_not_by_reassignment(tmp_path, monkeypatch):
    # This is the property the whole design depends on: every module that
    # already did `from config.settings import settings` must see the
    # update too, which only works if the object identity is preserved.
    monkeypatch.setattr("config.settings._PROJECT_ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env.staging").write_text("AURA_COMPRESSION_MODE=balanced\n")

    s = Settings(project_root=tmp_path)
    other_reference = s  # simulates a second module's `from config.settings import settings`
    assert s.compression_mode == "max"  # default

    s.reload_profile("staging")

    assert s is other_reference  # object identity preserved
    assert other_reference.compression_mode == "balanced"
    assert s.env == "staging"


def test_reload_profile_none_clears_back_to_base(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings._PROJECT_ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env.staging").write_text("AURA_COMPRESSION_MODE=balanced\n")

    s = Settings(project_root=tmp_path)
    s.reload_profile("staging")
    assert s.compression_mode == "balanced"

    s.reload_profile(None)
    assert s.compression_mode == "max"
    assert s.env is None


def test_typo_profile_name_does_not_crash_reload(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings._PROJECT_ENV_FILE", tmp_path / ".env")
    s = Settings(project_root=tmp_path)
    s.reload_profile("this_profile_does_not_exist")
    # No crash, and env is still reported honestly even though nothing
    # was actually overridden -- debuggable, not silently ignored.
    assert s.env == "this_profile_does_not_exist"
