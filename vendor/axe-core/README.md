# vendor/axe-core

Vendored copy of [axe-core](https://github.com/dequelabs/axe-core) v4.12.1,
the accessibility (a11y) rules engine used by `agents/capability/accessibility_adapter.py`
(Phase L1, see `docs/decisions.md`).

## Why vendored, not CDN-loaded

AURA is offline-first by design (`docs/decisions.md` D-002/D-018 --
network calls are opt-in and explicitly disclosed, never silently
defaulted). Loading axe-core from a CDN at scan time would mean every
accessibility check silently depends on an external network call and an
external party's uptime/content, for a target that may itself be an
internal/offline app under test. Vendoring the exact minified build here
means `accessibility_adapter.py` injects it via
`page.add_script_tag(path=...)` from local disk -- zero network calls
beyond whatever the test target itself already needed.

## Provenance

- Source: `npm pack axe-core` (registry.npmjs.org, version pinned to `4.12.1`)
- File: `axe.min.js` (the official minified UMD bundle, unmodified)
- License: `LICENSE` (Mozilla Public License 2.0, axe-core's own license --
  unmodified, included verbatim per its terms)
- `package.json.orig`: the untouched upstream package manifest, kept only
  for version/provenance reference -- not used by any AURA code.

## Updating

To bump the vendored version: `npm pack axe-core@<version>` in a scratch
directory, then replace `axe.min.js` and `LICENSE` here and update this
README's version references. `accessibility_adapter.py` doesn't hardcode
the version anywhere, so no code changes are needed for a version bump
alone.
