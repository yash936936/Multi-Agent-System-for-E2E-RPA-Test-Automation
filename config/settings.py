"""
Central configuration for AURA.

Single source of truth for paths, thresholds, and resource-compression
policy. Nothing here reaches out to the network — every default matches
values already specified in the design docs (TRD.md, PRD.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_project_root() -> Path:
    """
    Normal (non-frozen) run: this file lives at <project_root>/config/settings.py,
    so parent.parent is <project_root> -- unchanged from before.

    Frozen (PyInstaller) run: __file__ resolves inside PyInstaller's temporary
    extraction directory (sys._MEIPASS, e.g. /tmp/_MEIxxxxx on Linux or a
    similar %TEMP% path on Windows), which is deleted when the process exits.
    Writing reports/runtime/skills there means everything vanishes the moment
    the exe closes. Use the directory the actual .exe lives in instead, so
    output persists next to wherever the user put aura.exe.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class GuardrailSettings(BaseSettings):
    """Mirrors TRD.md §5.4 `tool_loop_guardrails` YAML block exactly."""

    warnings_enabled: bool = True
    hard_stop_enabled: bool = True

    warn_after_exact_failure: int = 2
    warn_after_same_tool_failure: int = 3
    warn_after_idempotent_no_progress: int = 2

    hard_stop_after_exact_failure: int = 5
    hard_stop_after_same_tool_failure: int = 8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AURA_", env_file=".env", extra="ignore")

    # --- root paths ---
    project_root: Path = Field(default_factory=_default_project_root)

    @property
    def runtime_dir(self) -> Path:
        return self.project_root / "runtime"

    @property
    def screenshots_dir(self) -> Path:
        return self.runtime_dir / "screenshots"

    @property
    def data_cache_dir(self) -> Path:
        return self.runtime_dir / "data_cache"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def skills_store_dir(self) -> Path:
        return self.project_root / "orchestrator" / "skills_store"

    @property
    def memory_dir(self) -> Path:
        return self.project_root / "orchestrator" / "memory"

    @property
    def requirements_input_dir(self) -> Path:
        return self.project_root / "requirements_input"

    # --- behavioral defaults (PRD/TRD) ---
    vision_confidence_threshold: float = 0.75  # TRD §5.3
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)

    # --- resource philosophy (TRD §3 / decisions D-005) ---
    # "maximal compression, on-demand, no fixed hardware baseline"
    compression_mode: str = "max"  # one of: max | balanced | off
    release_agent_after_call: bool = True

    # --- offline guarantee (decisions D-002) ---
    allow_network_calls: bool = False

    # --- OCR engine (optional override) ---
    # If pytesseract can't find the `tesseract` binary on PATH (common on
    # Windows), set this to the full path to tesseract.exe, either here or
    # via the AURA_TESSERACT_CMD env var / .env file. Leave as None to rely
    # on PATH (default, works out of the box on most Linux/Mac setups).
    tesseract_cmd: str | None = None

    # --- Planner backend selection (decisions.md D-010) ---
    # "heuristic": LocalHeuristicBackend, zero dependencies.
    # "local_llm": LocalLLMBackend -- a small GGUF model run fully on-device
    #   via llama-cpp-python. No network call, so this stays compatible
    #   with the offline guarantee (D-002) unlike AnthropicBackend, which
    #   requires allow_network_calls=True and remains available for
    #   reference/opt-in cloud use only.
    #
    # Left unset (None) by default so a bundled model can be auto-detected
    # (see _auto_detect_planner_backend below): drop a .gguf file in
    # models/ and AURA switches to local_llm with zero .env editing. Set
    # AURA_PLANNER_BACKEND explicitly in .env to override this.
    planner_backend: str | None = None
    local_llm_model_path: str | None = None  # path to a local .gguf file
    local_llm_max_tokens: int = 1024
    local_llm_context_size: int = 4096
    local_llm_temperature: float = 0.1  # low temperature: this is structured JSON extraction, not creative writing

    @property
    def models_dir(self) -> Path:
        return self.project_root / "models"

    def _find_bundled_model(self) -> Path | None:
        try:
            candidates = sorted(self.models_dir.glob("*.gguf"))
        except OSError:
            return None
        return candidates[0] if candidates else None

    @model_validator(mode="after")
    def _auto_detect_planner_backend(self) -> "Settings":
        # Explicit AURA_PLANNER_BACKEND in .env always wins. Only resolve
        # the "unset" case here, and only fill in local_llm_model_path when
        # the user didn't already point it somewhere themselves.
        if self.planner_backend is None:
            bundled = self._find_bundled_model()
            if bundled is not None:
                self.planner_backend = "local_llm"
                if self.local_llm_model_path is None:
                    self.local_llm_model_path = str(bundled)
            else:
                self.planner_backend = "heuristic"
        elif self.planner_backend == "local_llm" and self.local_llm_model_path is None:
            bundled = self._find_bundled_model()
            if bundled is not None:
                self.local_llm_model_path = str(bundled)
        return self

    def ensure_dirs(self) -> None:
        """Create all runtime/output directories if they don't exist yet."""
        for d in (
            self.screenshots_dir,
            self.data_cache_dir,
            self.reports_dir,
            self.skills_store_dir,
            self.memory_dir,
            self.requirements_input_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
