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

    # AD2 (docs/decisions.md D-062) -- when True (default), a retry whose
    # AA1 verification evidence (verification_source + raw_evidence) is
    # byte-identical to the immediately preceding attempt's evidence for
    # the same step short-circuits straight to HARD_STOP, bypassing the
    # count-based thresholds above entirely. This is deliberately
    # independent of exact_failure_count/same_tool_failure_count: a
    # count-based threshold can still be mid-count (e.g. 2 of 5) while a
    # retry has already produced literal zero new information, which is
    # exactly the D-055 incident this closes (self-healing retried three
    # times with an identical result before the count-based hard_stop
    # finally fired). Set False to fall back to pure count-based behavior.
    short_circuit_on_identical_evidence: bool = True



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

# Phase U (decisions.md D-043): valid dual_verification_tie_break values,
# shared between Settings' own field and agents/vision/executor.py's
# validation of it, same "one shared tuple, not two independent lists"
# convention as PLAYWRIGHT_BROWSER_CHOICES above.
DUAL_VERIFICATION_TIE_BREAK_CHOICES = ("highest_confidence", "prefer_dom", "prefer_ocr", "llm_semantic")


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

    # --- AF2 (docs/decisions.md, Phase AF): centralized logging ---
    # Every module already does `logging.getLogger(__name__)`, but nothing
    # in the codebase ever called logging.basicConfig() or attached a
    # handler -- so every one of those calls was silently going nowhere
    # persistent (Python's unconfigured-logger default: WARNING+ only, to
    # stderr, nothing below WARNING ever recorded, nothing ever written to
    # a file). AURA_LOG_LEVEL controls the level actually persisted to
    # logs/aura.log once config/logging_setup.py's configure_logging() is
    # called (done once, at CLI startup, in aura/main.py's main()).
    log_level: str = Field(default="INFO")


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
    def traces_dir(self) -> Path:
        # Phase Q (docs/decisions.md D-038): Playwright native trace .zip
        # files land here -- same category/lifecycle as videos_dir (local
        # generated run state, gitignored, not source), kept as its own
        # directory rather than reusing videos_dir since traces and videos
        # are independently toggleable and conceptually distinct artifacts.
        return self.runtime_dir / "traces"

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

    # --- Phase W gap-closure: Playwright must render on-screen, not just
    # in-process (decisions.md D-043's dual verification requires OCR --
    # a real mss capture of the OS screen, runtime/hooks/capture.py -- to
    # actually be able to see the same page the DOM locator is reading).
    # A headless=True browser is invisible to mss by construction: the
    # DOM side would keep working (it talks to Playwright directly), but
    # OCR would silently be scoring against whatever's on the real
    # desktop instead, never finding the target and quietly collapsing
    # every dual-verification case down to "single-method" (DOM-only) --
    # exactly the failure this setting fixes. Defaults to False (headed)
    # to match docs/README.md's existing requirement that "the target
    # application must be visible and the screen unlocked while AURA
    # runs." Set AURA_PLAYWRIGHT_HEADLESS=true to opt back into headless
    # for environments that only ever exercise the DOM path (e.g. CI
    # without a real display, where OCR/mss would raise NoDisplayError
    # anyway and dual verification never attempted OCR in the first
    # place).
    playwright_headless: bool = False

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

    # --- Phase O: data-seeding adapter (decisions.md D-036) ---
    # Off by default. Independent of capability_adapters_enabled above --
    # that flag is the general "is any outbound capability traffic
    # allowed" kill switch; this one is a second, deliberate gate specific
    # to db_seed_adapter.py, AURA's first-ever intentional database write
    # path. Both must be true for a seed call to actually run: the router
    # still enforces capability_adapters_enabled before any adapter is
    # even reached, and db_seed_adapter.py itself checks this flag before
    # doing anything else. Set AURA_ALLOW_DB_SEEDING=true to enable.
    allow_db_seeding: bool = False

    # --- Phase Q: Playwright native trace files (decisions.md D-038) ---
    # Off by default, same posture as record_video above -- trace .zip
    # files embed a DOM snapshot + screenshot per action, so they're
    # meaningfully larger than either screenshots or video and stay
    # opt-in. When True, runtime/hooks/browser.py wires Playwright's own
    # context.tracing.start()/stop() around the session lifecycle,
    # independently of record_video -- a run can have either, both, or
    # neither on at once.
    record_trace: bool = False

    # --- DOM-extractor exploration supplement (agents/vision/dom_extractor.py) ---
    # Off by default. When True and a live Playwright session is already
    # open (runtime.hooks.browser.has_active_page()), orchestrator/
    # ui_audit_runner.py's click-audit/explore loop supplements its
    # OCR-band candidate list with a live-DOM scan (icon-only controls,
    # custom div/span controls with no OCR-visible label text -- see
    # agents/vision/dom_extractor.py's module docstring for the full
    # rationale). Defaults off rather than on, unlike most detection
    # improvements in this codebase, for one specific reason: this is the
    # first source in the click-audit loop that can produce a *real*
    # on-screen click for an element whose only detectable signal is a
    # CSS cursor style (`cursor: pointer` on a div/span/li) -- broader
    # detection surface than either OCR text-matching or ARIA-role
    # matching, which both require some form of semantic labeling.
    # Enabling it trades a real chance of AURA finding genuinely missed
    # click targets against a real chance of it clicking a decorative
    # element that merely happens to be styled with a pointer cursor.
    # Turn on deliberately (AURA_ENABLE_DOM_EXTRACTOR=true) once you've
    # seen it behave correctly against your own site(s), not by default
    # for every user's first run.
    enable_dom_extractor: bool = False

    # --- Optional external integration: Composio (proposed D-046) ---
    # Off by default -- an explicit opt-in for the one thing this
    # codebase's own generic capability adapters structurally can't do:
    # OAuth2-token-lifecycle-managed tool access. agents/capability/
    # chatops_adapter.py (Slack/Teams) and defect_tracker_adapter.py
    # (Jira/TestRail/Zephyr/Xray-style tools) already cover static-
    # credential (webhook URL / bearer token / API key) integrations with
    # zero new dependencies -- Composio is deliberately NOT used for those,
    # it would just be a heavier second path to the same place. It's used
    # only for tools where the caller can't reasonably hand AURA a
    # long-lived static credential, e.g. Google Sheets: real usage needs
    # an OAuth2 access token refreshed against a refresh token on an
    # expiry clock, which neither of those adapters' "here's a header
    # dict, send it" model can do. Composio's own hosted OAuth connection
    # management is what's actually being reused here, not its wider
    # 250+-tool catalog -- see agents/capability/composio_adapter.py's
    # module docstring for the full scope boundary.
    enable_composio: bool = False
    composio_api_key: str | None = None  # populate via AURA_COMPOSIO_API_KEY
    # Composio's own identifier for which pre-authorized account/connection
    # to act through (created out-of-band via Composio's dashboard/CLI at
    # OAuth-grant time) -- AURA never handles the OAuth redirect/consent
    # flow itself, only ever a resolved connection to already-granted access.
    composio_connected_account_id: str | None = None

    # --- Phase U: OCR-then-DOM dual verification (decisions.md D-043) ---
    # Both OCR and DOM locators now always run (when a browser session
    # exists) rather than DOM-first/OCR-fallback -- see
    # agents/vision/executor.py's compilation step. These two settings
    # only affect what happens when *both* clear the confidence threshold:
    #
    # dual_verification_overlap_tolerance_px: how many pixels of slack are
    # allowed, in each direction, when checking whether OCR's matched
    # point falls inside (an expanded) DOM bounding box -- real DOM
    # bounding boxes and OCR-detected text-line centers rarely land on the
    # exact same pixel even for a genuine match, so a tolerance avoids
    # false "disagreement" on real agreement.
    #
    # dual_verification_tie_break: which method wins when OCR and DOM both
    # found *something* above threshold but at genuinely different
    # locations (a real disagreement, not just pixel jitter). One of:
    # "highest_confidence" (default -- whichever method scored higher),
    # "prefer_dom" (DOM wins outright -- appropriate if the DOM path is
    # trusted more for a given target app), "prefer_ocr" (OCR wins
    # outright). "llm_semantic" (Phase W, decisions.md D-047) -- ask a
    # configured LLM backend (CloudLLMBackend or HermesAgentBackend,
    # whichever is enabled/available) which candidate's matched text/role
    # more plausibly matches the step's own target_description, in plain
    # language, rather than a bare confidence-score comparison. Falls back
    # to "highest_confidence" automatically (logged, not silent) if no LLM
    # backend is enabled or the call fails -- this is meant to be a strictly
    # additive refinement on top of the existing tie-break logic, never a
    # new single point of failure. A disagreement is always logged (see
    # executor.py) and recorded in the step's verification_evidence
    # regardless of which tie-break mode is configured -- the losing
    # candidate is never silently dropped.
    dual_verification_overlap_tolerance_px: int = 40
    dual_verification_tie_break: str = "highest_confidence"

    # Off by default -- llm_semantic tie-break only activates the LLM
    # verifier call path if this is also explicitly enabled, mirroring
    # enable_cloud_planner/enable_hermes_agent's off-by-default posture
    # for anything that can make a network call.
    enable_llm_semantic_verifier: bool = False

    # Phase 1 (next-phase plan) -- gates agents/auditor/run_monitor.py's
    # independent second-opinion pass on every vision step's self-reported
    # outcome. Off by default: one extra LLM call per step has a real
    # latency cost (module docstring), so this stays opt-in until proven
    # not to bottleneck real runs. `RunEngine.run_spec(continuous_audit=...)`
    # can override this per-run (e.g. a CLI `--continuous-audit` flag)
    # without touching this default.
    enable_continuous_audit: bool = False

    # Phase 4 (next-phase plan) -- orchestrator/backend_router.py's
    # priority for the two cross-cutting LLM tasks it covers (semantic
    # tie-break, continuous-audit monitor). Same "hermes_first"/
    # "cloud_first" naming as planner_priority above, but this is a
    # separate setting -- deliberately not reusing planner_priority,
    # since Planner's own selection system is untouched by this router
    # (see backend_router.py's module docstring for why) and conflating
    # the two settings would make changing one silently affect the other.
    backend_router_priority: str = "hermes_first"

    # None (default) means "inherit backend_router_priority" -- set either
    # of these explicitly only if you want that specific task to use a
    # different backend order than the shared default (e.g. a fast local
    # Hermes instance for the frequent per-step tie-break, a stronger
    # cloud model for the much-less-frequent audit monitor).
    semantic_tie_break_backend_priority: str | None = None
    continuous_audit_backend_priority: str | None = None

    # backend_router.py sends a real (minimal) chat call to verify a
    # configured backend is actually reachable before committing a task
    # to it, rather than just checking "is it configured" -- this bounds
    # how long that probe is allowed to take before giving up and trying
    # the next candidate. Deliberately short: this is a reachability
    # check, not the real task call (which uses each client's own normal,
    # longer timeout).
    backend_router_health_check_timeout_s: float = 3.0


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

    # --- Phase V: dual API + local LLM generic backend (decisions.md D-044) ---
    # "cloud_llm": CloudLLMBackend -- a generic OpenAI-compatible HTTP client
    #   (no vendor SDK, works against any server implementing the
    #   /v1/chat/completions shape: OpenAI itself, Anthropic/others' OpenAI-
    #   compat endpoints, or a *local* OpenAI-compat server like Ollama/
    #   llama.cpp's server mode -- "cloud" names the code path, not a
    #   requirement that the endpoint be remote).
    #
    # Off by default (AURA_ENABLE_CLOUD_PLANNER=false) -- per D-002/D-018,
    # no network-capable planner path is enabled unless explicitly opted
    # into, mirroring record_video/allow_db_seeding's off-by-default
    # posture for anything that leaves the local machine or writes state.
    enable_cloud_planner: bool = False
    cloud_llm_base_url: str | None = None  # e.g. "https://api.openai.com/v1" or a local OpenAI-compat server URL
    cloud_llm_api_key: str | None = None
    cloud_llm_model: str | None = None

    # --- Phase W: real Hermes Agent integration (decisions.md D-047) ---
    # "hermes_agent": HermesAgentBackend -- talks to a running Hermes
    # Agent instance (https://github.com/NousResearch/hermes-agent) via
    # its OpenAI-compatible /v1/chat/completions API server
    # (orchestrator/hermes_client.py). This is what docs/PROJECT_OVERVIEW.md
    # originally described as AURA's orchestration layer; decisions.md D-006
    # replaced that with the in-repo kernel for the *dispatch* contract, but
    # no code path to a real Hermes instance existed at all until this
    # phase. Off by default -- same posture as enable_cloud_planner.
    enable_hermes_agent: bool = False
    hermes_agent_base_url: str | None = None  # e.g. "http://localhost:8642" (Hermes Agent's own default API_SERVER_PORT, started via `hermes gateway` -- not `hermes api-server`, which doesn't exist)
    hermes_agent_api_key: str | None = None  # Hermes's API_SERVER_KEY, if the instance requires one
    hermes_agent_model: str | None = None  # cosmetic per Hermes's own docs, but sent for clarity/logging

    # Phase X3 (decisions.md D-049): Planner.diagnose backend selection.
    # "heuristic" (default) is LocalHeuristicDiagnoser -- deterministic
    # keyword pattern-matching, zero dependencies. "hermes_agent" routes
    # root-cause diagnosis through the same Hermes Agent instance
    # configured for enable_hermes_agent/hermes_agent_base_url above,
    # letting Hermes's own memory/skill recall inform the diagnosis.
    # Explicit opt-in only -- not auto-detected, same posture as the
    # planner_backend="hermes_agent" default (D-047).
    diagnosis_backend: str = "heuristic"

    # Detection-matrix priority when settings.planner_backend is left
    # unset (auto-detect, see _auto_detect_planner_backend below):
    # "local_first" (default) prefers a bundled local .gguf model over
    # cloud when both are available; "cloud_first" reverses that. Either
    # way, generate_spec()'s own escalation policy (decisions.md D-044,
    # built on R3's retry-logging groundwork) can still fall through to
    # cloud at *runtime* if the chosen primary backend fails and cloud is
    # enabled -- this setting only controls the initial pick, not whether
    # escalation itself is possible.
    # "hermes_first" (Phase X follow-up to D-047) is opt-in only: it's the
    # one value that puts hermes_agent into the auto-detection matrix at
    # all (ahead of local_llm and cloud_llm), for operators who explicitly
    # want a reachable Hermes Agent instance auto-selected rather than
    # requiring AURA_PLANNER_BACKEND=hermes_agent set directly.
    planner_priority: str = "local_first"

    # If True, generate_spec() must never silently fall back to the
    # heuristic backend -- if no LLM backend (local or cloud) is actually
    # usable, fail fast and loudly instead. Off by default: the heuristic
    # backend existing as a always-available fallback is a deliberate
    # design property (decisions.md D-002), not something every deployment
    # wants to give up.
    require_llm_backend: bool = False

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

    def _cloud_llm_available(self) -> bool:
        # "Available" here means "configured", not "reachable" -- actually
        # pinging cloud_llm_base_url at Settings-construction time would
        # make every process startup depend on network reachability, which
        # is exactly the kind of implicit network dependency D-002/D-018
        # rule out. Real reachability failures surface at call time in
        # CloudLLMBackend.generate() instead, where generate_spec()'s
        # escalation policy (decisions.md D-044) can react to them.
        return bool(self.enable_cloud_planner and self.cloud_llm_base_url)

    def _hermes_agent_available(self) -> bool:
        # Same "configured, not reachable" posture as _cloud_llm_available.
        # Phase X (decisions.md D-047 follow-up): only counts as "available"
        # for auto-detection purposes at all when planner_priority is
        # explicitly "hermes_first" -- see _auto_detect_planner_backend
        # below for why hermes_agent isn't in the default local/cloud
        # matrix.
        return bool(self.enable_hermes_agent and self.hermes_agent_base_url)

    @model_validator(mode="after")
    def _auto_detect_planner_backend(self) -> "Settings":
        # Explicit AURA_PLANNER_BACKEND in .env always wins. Only resolve
        # the "unset" case here, and only fill in local_llm_model_path when
        # the user didn't already point it somewhere themselves.
        if self.planner_backend is None:
            bundled = self._find_bundled_model()
            local_available = bundled is not None
            cloud_available = self._cloud_llm_available()

            # Detection matrix (Phase V, decisions.md D-044; extended Phase X
            # follow-up to D-047): pick the highest-priority *available* LLM
            # backend; planner_priority only breaks the tie when more than
            # one is available. Heuristic is the guaranteed-available last
            # resort, unless require_llm_backend demands failing fast
            # instead.
            #
            # hermes_agent is deliberately excluded from the default
            # "local_first"/"cloud_first" orders -- a reachable Hermes
            # instance is a much weaker signal of intent than a
            # deliberately-placed .gguf file or a deliberately-set
            # cloud_llm_base_url (D-047). It only enters the matrix at all
            # if an operator explicitly opts in via
            # planner_priority="hermes_first", which puts it first.
            if self.planner_priority not in ("local_first", "cloud_first", "hermes_first"):
                raise ValueError(
                    f"Unknown settings.planner_priority '{self.planner_priority}'. "
                    "Valid options: 'local_first', 'cloud_first', 'hermes_first'."
                )
            hermes_available = self._hermes_agent_available()
            if self.planner_priority == "hermes_first":
                order = ["hermes_agent", "local_llm", "cloud_llm"]
            elif self.planner_priority == "cloud_first":
                order = ["cloud_llm", "local_llm"]
            else:
                order = ["local_llm", "cloud_llm"]
            available = {
                "local_llm": local_available,
                "cloud_llm": cloud_available,
                "hermes_agent": hermes_available,
            }
            chosen = next((name for name in order if available[name]), None)

            if chosen == "local_llm":
                self.planner_backend = "local_llm"
                if self.local_llm_model_path is None:
                    self.local_llm_model_path = str(bundled)
            elif chosen == "cloud_llm":
                self.planner_backend = "cloud_llm"
            elif chosen == "hermes_agent":
                self.planner_backend = "hermes_agent"
            elif self.require_llm_backend:
                raise ValueError(
                    "settings.require_llm_backend is True but no LLM backend is usable: "
                    "no bundled .gguf model found under models_dir, and settings.enable_cloud_planner "
                    "is False (or cloud_llm_base_url is unset). Either place a .gguf model in models/, "
                    "set AURA_ENABLE_CLOUD_PLANNER=true with AURA_CLOUD_LLM_BASE_URL configured, "
                    "or unset AURA_REQUIRE_LLM_BACKEND to allow the heuristic fallback."
                )
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
