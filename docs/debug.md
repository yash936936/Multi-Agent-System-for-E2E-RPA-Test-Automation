---
type: debug-protocol
project: AURA (Multi-Agent-System-for-E2E-RPA-Test-Automation)
applies_to: every AI coding session that touches this repo
last_updated: 2026-07-13
---

# DEBUG.md — Mandatory Debug Protocol for AI Contributors

## Purpose
This file is a standing instruction, not a one-time task. Every time an AI agent
(Claude, or any other coding assistant) modifies, generates, or reviews code in
this repository, it must run this protocol before declaring work "done." AURA has
already suffered real, recorded bugs from partial edits — a renamed schema
(`CapabilityResult` → `CapabilityCheckResult`) that wasn't propagated to seven
call sites, a `capability_router.py` reading a nonexistent `payload.step`
attribute, a service layer that silently never called `RunEngine`. This file
exists so that class of bug doesn't happen again.

Read `context.md` (repo root) first. It tells you which docs are authoritative
and where data/config actually live. This file tells you *how to verify* any
change you make against that context.

---

## 1. When this protocol runs
Run the full checklist below any time you:
- Add, edit, or delete a `.py`, `.md`, `.yaml`, `.json`, `.j2`, `.html`, or `.js` file in this repo.
- Rename a function, class, schema field, config key, or CLI command.
- Add a new dependency.
- Touch anything under `agents/`, `orchestrator/`, `api/`, `aura/`, `runtime/`, `config/`, `webui/`.
- Merge in code extracted from an external repo (see `context.md` → "External repo extraction").

Do not skip this because a change "looks small." The schema-rename bug above was
a single rename that broke seven files.

---

## 2. Line-by-line review checklist

For every file you touched or that imports/is imported by a file you touched,
walk it top to bottom and check:

### 2.1 Syntax & imports
- [ ] File parses (no syntax errors). Run `python -m py_compile <file>` for Python.
- [ ] Every `import` resolves to a real module/package that is actually installed
      (check `pyproject.toml` / `requirements` — don't assume a library is present).
- [ ] No unused imports left behind after an edit (`pyflakes` / `ruff` clean —
      AURA's own `aura debug` command wraps `ruff` for exactly this; use it:
      `python -m aura.main debug <path>` or `ruff check <path>`).
- [ ] No circular imports introduced.

### 2.2 Names & signatures
- [ ] Every function/method call matches the current signature of the function
      being called (arg count, names, types) — not a signature from memory or
      from an older version of the file.
- [ ] Every attribute access (`obj.field`) matches a field that actually exists
      on that class/schema **right now**. Grep for the class definition and
      confirm the field name before trusting it.
- [ ] If you renamed a schema field, class, or constant, grep the *entire repo*
      for the old name and update every call site — do not rely on memory of
      "where it's probably used." Example command:
      `grep -rn "OldName" --include="*.py" .`
- [ ] Enum/constant values referenced in adapters (`orchestrator/schemas.py`
      `CapabilityType`) match an entry actually registered in
      `orchestrator/capability_adapter.py::default_registry()`.

### 2.3 Logic
- [ ] Every branch (`if`/`elif`/`else`, `match`/`case`) has been mentally
      traced with at least one concrete example input.
- [ ] Every action parameter that is parsed but should be branched on (see the
      known `cloud_adapter.py` "action parsed but never branched on" gap in
      `STATUS.md`) is actually checked — flag, don't silently drop, any
      unhandled case.
- [ ] No stub / placeholder logic is left where real logic was requested.
      AURA's own history has a real example of this: `api/routers/runs.py`
      once flipped every run to `"passed"` with a `# Hook into RunEngine
      here...` comment instead of calling `RunEngine`. Search new code for
      `TODO`, `FIXME`, `pass  #`, `# Hook`, `NotImplementedError` and either
      resolve them or explicitly document them in `STATUS.md` as a known gap
      — never leave them silently disguised as working code.
- [ ] Retry/heal loops have a hard bound (see `orchestrator/guardrails.py`) —
      never an unbounded `while True` without an exit condition.

### 2.4 Missing files / missing dependencies
- [ ] Every file path referenced in code (config paths, template paths, model
      paths, `.gguf` paths, skill/memory store paths) actually exists or is
      created before first use. Check `config/settings.py` for the canonical
      path definitions instead of hardcoding a new one.
- [ ] Every new third-party dependency is added to `pyproject.toml` (not just
      `pip install`ed locally and forgotten).
- [ ] Any new adapter under `agents/capability/` is registered in
      `orchestrator/capability_adapter.py::default_registry()` AND in
      `config/tool_registry.yaml` AND has a corresponding `CapabilityType`
      entry in `orchestrator/schemas.py`. Missing any one of these three is a
      confirmed historical bug class in this repo — check all three, every time.

### 2.5 Cross-file consistency
- [ ] Schema types used in `orchestrator/run_engine.py`,
      `orchestrator/capability_router.py`, and any `agents/capability/*.py`
      adapter agree on field names (this is the exact bug class recorded in
      `progress.md`'s 2026-07-04 entry — do not reintroduce it).
- [ ] CLI commands added under `aura/cli/` are registered in `aura/main.py`
      and documented in `README.md`'s CLI reference table.
- [ ] Any doc claim ("X is implemented," "Y tests passing") is checked against
      actual test results before being written — run the test suite, don't
      assume. See §3.

### 2.6 Tests
- [ ] Run the full suite: `pytest -q` from repo root.
- [ ] If you added/changed behavior, there is a new or updated test covering it.
- [ ] Record the before/after pass count. AURA's docs track this explicitly
      (e.g. "205 → 225 tests") — follow that convention in `progress.md`.
- [ ] Do not mark a task complete with failing or skipped tests without an
      explicit, documented reason in `STATUS.md`.

---

## 3. After the checklist: verification, not assertion
Before writing "done," "fixed," or "implemented" anywhere (chat, commit
message, or `.md` file):
1. Actually run the code path you changed (or the relevant test) and observe
   the real output — don't infer success from reading the code.
2. If you cannot run it in this environment, say so explicitly and mark the
   change "unverified" rather than "done."
3. If a claim in an existing `.md` file becomes false because of your change,
   update that file in the same pass. Stale docs are treated as bugs in this
   project (see `STATUS.md`'s own "Needs review" section for the pattern to
   follow).

---

## 4. Reporting format
When you finish a debug pass, report in this shape (mirrors this repo's own
`STATUS.md` conventions):

```
## Debug pass — <date>
### Files reviewed
- path/to/file.py — <clean | N issues found>

### Issues found & fixed
- <file>: <what was broken> → <what you changed> → <how you verified it>

### Issues found & NOT fixed (flagged for human decision)
- <file>: <what's broken> — <why you're not silently fixing it>

### Test results
Before: X/X passing
After:  Y/Y passing

### Docs updated
- <list any .md files you updated because this change made them stale>
```

---

## 5. Hard rules (never violate)
1. Never silently paper over a missing dependency, missing file, or failing
   test by removing the code that exercises it. Flag it instead.
2. Never leave a renamed identifier half-migrated. Grep the whole repo.
3. Never claim "implemented" or "passing" without having actually run it.
4. Never introduce an unbounded retry/heal loop (violates FR7 / guardrails).
5. Never add a capability adapter without registering it in all three places
   listed in §2.4.
6. Never delete or bypass this file's checklist because a change "seems safe."
