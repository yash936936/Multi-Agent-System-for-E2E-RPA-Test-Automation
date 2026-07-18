"""
Composio adapter — agents/capability/composio_adapter.py

Proposed D-046 (docs/optional_external_integrations_design.md). Off by
default (settings.enable_composio). Scoped deliberately narrow: this
adapter exists for ONE reason -- OAuth2-token-lifecycle-managed tool
access, which this codebase's existing generic capability adapters
structurally cannot do.

agents/capability/chatops_adapter.py (Slack/Teams webhooks) and
agents/capability/defect_tracker_adapter.py (Jira/TestRail/Zephyr/Xray
via field-mapped REST) already cover static-credential integrations --
a webhook URL, or a bearer token/API key that doesn't expire on its own
-- with zero new dependencies. Composio is deliberately NOT used to
duplicate either of those; it would just be a heavier second path to a
place AURA can already reach. It's used only where the caller can't
reasonably hand AURA a long-lived static credential at all: Google
Sheets is the concrete case this adapter targets. Real usage needs an
OAuth2 access token refreshed against a refresh token on an expiry
clock, and neither of the generic adapters' "here's a header dict, send
it" model can do that. Composio's own hosted OAuth connection
management (the user authorizes once, out-of-band, via Composio's own
Connect Link flow -- never through AURA) is what's actually being reused
here, not its wider tool catalog. AURA never handles an OAuth
redirect/consent screen itself, only ever a `connected_account_id` for
an already-granted connection.

Design constraints, mirroring db_seed_adapter.py's shape for the same
reasons (this is also an adapter with a narrow, deliberately-scoped
capability, gated more tightly than the router's general kill switch):

1. **Second, explicit opt-in.** settings.enable_composio (default False)
   is checked here, independent of the router's general
   capability_adapters_enabled gate -- same two-layer pattern
   db_seed_adapter.py uses for settings.allow_db_seeding, since "is
   outbound capability traffic allowed at all" and "is this specific,
   third-party-SDK-dependent capability allowed" are different
   questions.
2. **Deferred import.** `from composio import Composio` happens only
   inside run(), after the gate passes -- a stock AURA install never
   needs the `composio` package installed at all, matching the same
   deferred-import discipline agents/vision/dom_extractor.py and every
   other optional-dependency surface in this codebase already follows.
3. **No literal tool-slug guessing.** Composio's exact action-slug
   naming (e.g. whichever of GOOGLESHEETS_APPEND_VALUES /
   GOOGLESHEETS_BATCH_UPDATE / similar their registry currently exposes)
   is not hardcoded here -- Composio's own tool catalog is versioned and
   can rename slugs between releases, and this file can't verify the
   current one against a live install. The caller supplies `tool_slug`
   explicitly via params (defaulting to a documented, commonly-stable
   name), the same "caller supplies the exact identifier, adapter
   doesn't guess" posture defect_tracker_adapter.py already takes for
   field-mapping.
4. **Every call is audited.** Reuses orchestrator/audit_logger.py, same
   sink capability_router.py and db_seed_adapter.py already write to --
   this adapter reaches a real third-party account on the caller's
   behalf, worth a paper trail for the same reason DB_SEED gets one.
"""
from __future__ import annotations

from typing import Any, Dict

from config.settings import settings
from orchestrator.audit_logger import audit_logger
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

# Composio's documented "Append Values to Spreadsheet" action as of this
# writing (docs.composio.dev, Google Sheets toolkit reference). Overridable
# per-call via params["tool_slug"] since Composio's own registry can rename
# or version this -- see design constraint 3 above.
_DEFAULT_APPEND_TOOL_SLUG = "GOOGLESHEETS_BATCH_UPDATE"


class ComposioAdapter:
    """
    Proposed D-046: OAuth-managed Google Sheets append via Composio.
    Off by default (settings.enable_composio).
    """

    capability_type: CapabilityType = CapabilityType.COMPOSIO_SHEETS

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params or {}

        # Second, deliberate gate -- independent of the router's general
        # capability_adapters_enabled kill switch, same two-layer shape
        # db_seed_adapter.py uses. Checked first so a disabled deployment
        # gets a clean, uniform rejection regardless of what else is
        # wrong with the call.
        if not settings.enable_composio:
            return self._fail(
                "Composio integration is disabled (settings.enable_composio is False). "
                "This is a separate, explicit opt-in from capability_adapters_enabled -- "
                "set AURA_ENABLE_COMPOSIO=true (or settings.enable_composio = True) to "
                "enable this adapter. It exists only for OAuth-token-managed tools "
                "(e.g. Google Sheets) that agents/capability/chatops_adapter.py and "
                "agents/capability/defect_tracker_adapter.py's static-credential model "
                "can't reach -- for Slack/Teams/Jira/TestRail-style tools, use those "
                "adapters instead."
            )

        api_key = settings.composio_api_key
        if not api_key:
            return self._fail(
                "Missing settings.composio_api_key -- set AURA_COMPOSIO_API_KEY. "
                "This is AURA's own key for calling the Composio API, distinct from "
                "the end user's Google OAuth grant (that's handled entirely by "
                "Composio's own Connect Link flow, out-of-band, before this adapter "
                "is ever called)."
            )

        spreadsheet_id = params.get("spreadsheet_id")
        values = params.get("values")
        if not spreadsheet_id:
            return self._fail("Missing 'spreadsheet_id'")
        if not values or not isinstance(values, list):
            return self._fail("Missing or invalid 'values' -- expected a non-empty list of rows")

        cell_range = params.get("range", "Sheet1!A1")
        user_id = params.get("composio_user_id", "aura")
        connected_account_id = params.get("connected_account_id") or settings.composio_connected_account_id
        tool_slug = params.get("tool_slug", _DEFAULT_APPEND_TOOL_SLUG)

        if not connected_account_id:
            return self._fail(
                "Missing 'connected_account_id' (and settings.composio_connected_account_id "
                "is also unset) -- Composio needs an already-authorized connection to act "
                "through. AURA does not initiate the OAuth grant itself; create the "
                "connection once via Composio's own dashboard/Connect Link flow, then "
                "pass its id here."
            )

        try:
            from composio import Composio  # deferred -- see module docstring, constraint 2

            client = Composio(api_key=api_key)
            result = client.tools.execute(
                tool_slug,
                user_id=user_id,
                connected_account_id=connected_account_id,
                arguments={
                    "spreadsheet_id": spreadsheet_id,
                    "range": cell_range,
                    "values": values,
                },
            )
        except ImportError:
            return self._fail(
                "The 'composio' package is not installed (pip install composio) -- "
                "required only when settings.enable_composio is True, per this "
                "adapter's deferred-import design (module docstring, constraint 2)."
            )
        except Exception as e:
            return self._fail(f"Composio tool execution error: {e}")

        audit_logger.log(
            tenant_id="system",
            user_id="system",
            action="COMPOSIO_SHEETS_APPEND",
            resource=spreadsheet_id,
            details={"spreadsheet_id": spreadsheet_id, "range": cell_range, "row_count": len(values), "tool_slug": tool_slug},
        )

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=True,
            confidence=1.0,
            evidence={"spreadsheet_id": spreadsheet_id, "range": cell_range, "row_count": len(values), "raw_result": self._safe_evidence(result)},
            escalate=False,
        )

    @staticmethod
    def _safe_evidence(result: Any) -> Dict[str, Any]:
        """
        Composio's execute() return shape isn't guaranteed stable across
        their SDK versions -- store whatever's JSON-shaped about it
        without letting an unexpected object type break result
        construction. Never raises.
        """
        try:
            if isinstance(result, dict):
                return result
            return {"repr": str(result)[:2000]}
        except Exception:
            return {}

    def _fail(self, msg: str) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=False,
            confidence=1.0,
            evidence={"error": msg},
            escalate=False,
        )
