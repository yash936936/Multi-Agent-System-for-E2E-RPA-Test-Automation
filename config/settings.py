"""
Central configuration for AURA.

Single source of truth for paths, thresholds, and resource-compression
policy. Nothing here reaches out to the network — every default matches
values already specified in the design docs (TRD.md, PRD.md).
"""
from __future__ import annotations

import os
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



# Resolve .env relative to the project root (parent of this config/ directory)
# so AURA_* variables are found regardless of the current working directory.
# This is critical for global `aura` usage (e.g. running from C:\Users\prakh
# after install) — a relative ".env" would resolve to the shell's cwd, not
# the project folder where install.bat wrote AURA_TESSERACT_CMD.
_PROJECT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _resolve_env_files(profile: str | None, base_env_file: Path = None) -> tuple[Path, ...]:
    """
    Phase G1 (decisions.md D-025): environment-profile support. Base `.env`
    always loads first; `.env.<profile>` (if it exists) loads second and
    wins on any key it also sets -- pydantic-settings applies later files
    in `env_file` with higher priority, so this is a genuine override
    layer, not a full replacement of the base file. A profile with no
    matching `.env.<profile>` file is not an error -- it just means
    "nothing to override," so a typo in the profile name silently falls
    back to base-only behavior rather than crashing. (Documented, not
    hidden: `Settings.env_profile` below reports which profile, if any,
    was actually applied, so `aura --env typo ...` is debuggable.)

    base_env_file defaults to the fixed project-root .env (used at class
    definition time, before any Settings instance -- and therefore no
    project_root override -- exists yet). Settings.reload_profile() passes
    self.project_root / ".env" explicitly instead, so a project_root
    overridden in tests (or via AURA_PROJECT_ROOT) is respected on reload
    too, rather than reload always looking next to this source file.
    """
    base = base_env_file if base_env_file is not None else _PROJECT_ENV_FILE
    files: list[Path] = [base]
    if profile:
        profile_file = base.parent / f".env.{profile}"
        if profile_file.exists():
            files.append(profile_file)
    return tuple(files)


# Read AURA_ENV directly from the process environment (not via a pydantic
# field) at *module import time*, because pydantic-settings needs the
# env_file list decided before the Settings class is even defined --
# there's no way to make env_file itself depend on a field of the class
# it configures. Settings.env below still exposes this normally as a
# regular field for introspection/consistency once the class exists.
_INITIAL_ENV_PROFILE = os.environ.get("AURA_ENV") or None


# Phase I1 (decisions.md D-030): valid Playwright browser engine choices,
# shared between Settings.playwright_browser's default/validation and
# aura/main.py's --browser CLI option so the two never drift apart.
PLAYWRIGHT_BROWSER_CHOICES = ("chromium", "firefox", "webkit")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AURA_",
        env_file=_resolve_env_files(_INITIAL_ENV_PROFILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- environment profile (Phase G1, decisions.md D-025) ---
    # Maps to AURA_ENV. Populated from whichever profile was actually
    # resolved at construction time (see _resolve_env_files) -- exposed as
    # a real field so `aura --env staging ...`/settings.env_profile is
    # introspectable rather than only living in a module-level variable.
    env: str | None = Field(default=None)


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
    def baselines_dir(self) -> Path:
        # Phase G3 (decisions.md D-027): stored visual-regression baseline
        # images, one per baseline_key, persisted across runs (unlike
        # screenshots_dir, which is per-run). Lives under runtime/ since
        # it's local generated state, not source -- same category as
        # screenshots/data_cache, gitignored the same way.
        return self.runtime_dir / "baselines"

    @property
    def videos_dir(self) -> Path:
        # Phase I2 (docs/decisions.md D-030): Playwright-recorded videos for
        # the DOM path, and slideshow manifests for the OS/pixel path, both
        # land here. Same category as baselines_dir/screenshots_dir --
        # local generated run state, gitignored, not source.
        return self.runtime_dir / "videos"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def skills_store_dir(self) -> Path:
        return self.project_root / "orchestrator" / "skills_store"

    @property
    def memory_dir(self) -> Path:
        # NOTE: intentionally NOT named "memory" -- orchestrator/memory.py is a
        # module in this same package, and a directory literally named
        # "memory" sitting next to it creates a module/package name collision
        # (orchestrator/memory.py vs orchestrator/memory/). Which one Python's
        # FileFinder picks depends on filesystem directory-entry order, which
        # differs between OSes -- this is why `from orchestrator.memory
        # import RunMemoryStore` worked on some machines and raised
        # ImportError on others (e.g. Windows). Keep this directory name
        # distinct from any sibling module name.
        return self.project_root / "orchestrator" / "memory_store"

    @property
    def requirements_input_dir(self) -> Path:
        return self.project_root / "requirements_input"

    @property
    def triggers_pending_dir(self) -> Path:
        return self.project_root / "triggers" / "pending"

    @property
    def triggers_processed_dir(self) -> Path:
        return self.project_root / "triggers" / "processed"

    # --- behavioral defaults (PRD/TRD) ---
    vision_confidence_threshold: float = 0.75  # TRD §5.3

    # Interactive / human-in-the-loop mode (WAIT_FOR_HUMAN_ACTION step type).
    # Polling, not a single check: the loop re-screenshots every
    # `human_action_poll_interval_seconds` and compares against the
    # baseline, so it reacts as soon as you act instead of on a fixed
    # timer. `human_action_timeout_seconds = 0` means wait indefinitely
    # (the default -- a human-in-the-loop step should not silently give up
    # just because someone stepped away from the keyboard for a minute).
    human_action_poll_interval_seconds: float = 2.0
    human_action_timeout_seconds: int = 0
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)

    # --- resource philosophy (TRD §3 / decisions D-005) ---
    # "maximal compression, on-demand, no fixed hardware baseline"
    compression_mode: str = "max"  # one of: max | balanced | off
    release_agent_after_call: bool = True

    # --- offline guarantee (decisions D-002, hardened by D-018) ---
    # There used to be an `allow_network_calls` escape-hatch flag here,
    # gating the now-removed AnthropicBackend. It's gone, not just unused:
    # the planner has no network-capable code path left at all, so there
    # is nothing left for a flag like this to gate. Capability adapters
    # (agents/capability/*.py) remain the sole intentional network/
    # filesystem surface, and each one requires its own explicit
    # `params.target`/connection string from the caller -- see TRD.md §9.

    # --- Phase D: capability-adapter egress controls (decisions D-020) ---
    # Hard kill switch: when False, orchestrator.capability_router rejects
    # every CapabilityCheckInput before any adapter runs (Vision/Playwright/
    # Planner are untouched -- this only gates the intentionally-outbound
    # adapters: api, database, email, file_system, excel, pdf_ocr, cloud,
    # azure_blob, gcp_storage, sharepoint, workflow, chat_ops, link_check,
    # automation_anywhere, web_validation). One flag for a fully air-gapped
    # deployment, instead of needing to know every adapter's name.
    capability_adapters_enabled: bool = True

    # Egress allowlist: when set, a capability's target host must match one
    # of these entries (exact match, or be a subdomain of one) or the
    # request is rejected before the adapter runs. None (default) = no
    # restriction beyond the kill switch above -- this is opt-in hardening,
    # not a default behavior change that could break existing specs.
    # Non-network capabilities (local file_system/excel/pdf_ocr targets,
    # and FAKE) are exempt from host matching -- there is no host to check.
    allowed_capability_hosts: list[str] | None = None

    # --- Phase I1: cross-browser support (decisions.md D-030) ---
    # Which Playwright browser engine runtime/hooks/browser.py launches.
    # "chromium" (default, unchanged behavior) | "firefox" | "webkit".
    # Validated in the model_validator below rather than a Literal type so
    # an invalid value degrades to a clear settings-level error instead of
    # a cryptic AttributeError deep inside browser.py's getattr() lookup.
    playwright_browser: str = "chromium"

    # --- Phase I2: video recording (decisions.md D-030) ---
    # Off by default -- opt-in, since video files are meaningfully larger
    # than screenshots and most runs don't need them. When True and the
    # DOM/Playwright path is active, runtime/hooks/browser.py records a
    # real video via Playwright's native `record_video_dir`. When the
    # OS/pixel fallback path is active instead (no live accessibility
    # tree -- native desktop targets), runtime/hooks/video_recorder.py
    # produces an honestly-labeled step-boundary "slideshow" (a manifest
    # referencing each step's already-captured screenshot in order), never
    # claimed to be continuous video.
    record_video: bool = False

    # --- OCR engine (optional override) ---
    # If pytesseract can't find the `tesseract` binary on PATH (common on
    # Windows), set this to the full path to tesseract.exe, either here or
    # via the AURA_TESSERACT_CMD env var / .env file. Leave as None to rely
    # on PATH (default, works out of the box on most Linux/Mac setups).
    tesseract_cmd: str | None = None

    # --- Planner backend selection (decisions.md D-010, D-018) ---
    # "heuristic": LocalHeuristicBackend, zero dependencies.
    # "local_llm": LocalLLMBackend -- a small GGUF model run fully on-device
    #   via llama-cpp-python. No network call. This is now the only
    #   LLM-backed path -- AnthropicBackend was removed entirely (D-018),
    #   not just disabled.
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

    # --- OAuth providers (optional; unset = provider disabled in UI) ---
    # Populate via env vars AURA_GOOGLE_CLIENT_ID / AURA_GOOGLE_CLIENT_SECRET
    # and AURA_GITHUB_CLIENT_ID / AURA_GITHUB_CLIENT_SECRET, or a .env file.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    oauth_redirect_base: str = "http://localhost:8000"

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

    def reload_profile(self, profile: str | None) -> None:
        """
        Phase G1 (decisions.md D-025): switches the active environment
        profile *after* the module-level `settings` singleton already
        exists -- used by `aura --env <name> <command>` (aura/main.py's
        top-level callback runs before any subcommand). Deliberately
        mutates every field on `self` in place rather than reassigning
        the module-level `settings` name to a new object: dozens of
        modules already did `from config.settings import settings` at
        their own import time, which binds a reference to this exact
        object -- rebinding the module attribute wouldn't update any of
        those already-bound references, but mutating the object every
        one of them points to does.
        """
        os.environ["AURA_ENV"] = profile or ""
        if not profile:
            os.environ.pop("AURA_ENV", None)

        type(self).model_config = SettingsConfigDict(
            env_prefix="AURA_",
            env_file=_resolve_env_files(profile, self.project_root / ".env"),
            env_file_encoding="utf-8",
            extra="ignore",
        )
        fresh = Settings(project_root=self.project_root)
        for field_name in type(self).model_fields:
            setattr(self, field_name, getattr(fresh, field_name))

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
