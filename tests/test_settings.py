from __future__ import annotations

from config.settings import Settings


def test_no_bundled_model_defaults_to_heuristic(tmp_path):
    s = Settings(project_root=tmp_path, _env_file=None)
    assert s.planner_backend == "heuristic"
    assert s.local_llm_model_path is None


def test_bundled_model_auto_selects_local_llm(tmp_path):
    (tmp_path / "models").mkdir()
    model_file = tmp_path / "models" / "qwen2.5-3b-instruct-q4_k_m.gguf"
    model_file.write_bytes(b"stub")

    s = Settings(project_root=tmp_path, _env_file=None)
    assert s.planner_backend == "local_llm"
    assert s.local_llm_model_path == str(model_file)


def test_explicit_backend_env_value_always_wins(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "some-model.gguf").write_bytes(b"stub")

    s = Settings(project_root=tmp_path, planner_backend="heuristic", _env_file=None)
    assert s.planner_backend == "heuristic"
    assert s.local_llm_model_path is None


def test_explicit_local_llm_path_not_overridden_by_bundled_model(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "bundled.gguf").write_bytes(b"stub")
    other_path = str(tmp_path / "elsewhere.gguf")

    s = Settings(project_root=tmp_path, planner_backend="local_llm", local_llm_model_path=other_path, _env_file=None)
    assert s.local_llm_model_path == other_path


def test_multiple_bundled_models_picks_first_alphabetically(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "b-model.gguf").write_bytes(b"stub")
    (tmp_path / "models" / "a-model.gguf").write_bytes(b"stub")

    s = Settings(project_root=tmp_path, _env_file=None)
    assert s.local_llm_model_path.endswith("a-model.gguf")