"""
orchestrator/http_retry.py

AF5 (docs/decisions.md, Phase AF) -- shared retry-with-backoff for the
transient network failures this whole reliability push started from:
a real run that hit both `HermesAgentClient` connection-refused AND
`CloudLLMBackend`'s Gemini endpoint returning a 503 "high demand, try
again later" in the same session. Neither call site retried at all --
one bad moment from either backend meant an immediate escalation/failure,
even though both failure classes are frequently transient by nature
(a backend that's still starting up, a cloud provider briefly over
capacity).

Deliberately narrow about what's retried:
  - Transport-level failures (`httpx.TransportError` -- covers
    ConnectError, ConnectTimeout, ReadTimeout, etc.) -- these are exactly
    the "target machine actively refused it" shape.
  - HTTP status codes that are conventionally transient: 429 (rate
    limited), 500/502/503/504 (server-side overload/gateway issues).
  - NOT retried: 400/401/403/404 and other 4xx -- retrying a genuine bad
    request, bad API key, or wrong URL just delays surfacing a real
    configuration error to the operator. Retrying those would make
    debugging *worse*, not more reliable.

`post_with_retry()` is a drop-in replacement for `client.post(...)` --
same return contract (an `httpx.Response`, whether the final attempt
succeeded or not; callers keep their own existing
`if response.status_code != 200: raise ...` handling unchanged). This
was a deliberate design choice so wiring it into
`CloudLLMBackend.generate()` and `HermesAgentClient.chat()` needed to
touch only the one line making the actual request, not their
surrounding error-handling logic.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

import httpx

from orchestrator.decision_trace_log import decision_trace_log

_logger = logging.getLogger(__name__)

DEFAULT_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def post_with_retry(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any],
    max_attempts: int = 3,
    base_delay_s: float = 1.0,
    max_delay_s: float = 10.0,
    retryable_statuses: frozenset[int] = DEFAULT_RETRYABLE_STATUSES,
    sleep_fn: Callable[[float], None] = time.sleep,
    caller_name: str = "http_retry",
    decision_trace_category: Optional[str] = None,
) -> httpx.Response:
    """
    Attempts `client.post(url, headers=headers, json=json)` up to
    `max_attempts` times, with exponential backoff (base_delay_s * 2**n,
    capped at max_delay_s) between attempts, retrying only on:
      - httpx.TransportError (connection refused, timeout, etc.)
      - a response whose status_code is in retryable_statuses

    On the last attempt, whatever happens is returned/raised as-is --
    a final TransportError propagates to the caller (same as an
    unwrapped client.post() would), and a final retryable-status response
    is returned normally so the caller's existing
    `if response.status_code != 200: raise ...` handling still fires,
    completely unchanged.

    decision_trace_category, if given, records exactly one outcome via
    orchestrator/decision_trace_log.py once retries are exhausted
    ("gave_up_after_retries") or once a retry actually recovered
    ("recovered_after_retry") -- not one record per attempt, since
    every attempt already goes through this module's own logger (AF2
    persists that to logs/aura.log); the decision trace is for the
    higher-level "was this eventually a problem" question AF3/AF4
    already answer for the planner/capability-adapter categories.
    """
    last_exc: Exception | None = None
    last_response: httpx.Response | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.post(url, headers=headers, json=json)
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt == max_attempts:
                _logger.warning(
                    "%s: attempt %d/%d to %s failed (%s: %s) -- out of retries, raising.",
                    caller_name, attempt, max_attempts, url, type(exc).__name__, exc,
                )
                if decision_trace_category:
                    _record_outcome(decision_trace_category, "gave_up_after_retries", caller_name, str(exc))
                raise
            delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
            _logger.warning(
                "%s: attempt %d/%d to %s failed (%s: %s) -- retrying in %.1fs.",
                caller_name, attempt, max_attempts, url, type(exc).__name__, exc, delay,
            )
            sleep_fn(delay)
            continue

        if response.status_code not in retryable_statuses:
            if attempt > 1 and decision_trace_category:
                _record_outcome(decision_trace_category, "recovered_after_retry", caller_name, f"succeeded on attempt {attempt}")
            return response

        last_response = response
        if attempt == max_attempts:
            _logger.warning(
                "%s: attempt %d/%d to %s got retryable status %d -- out of retries, returning it as-is.",
                caller_name, attempt, max_attempts, url, response.status_code,
            )
            if decision_trace_category:
                _record_outcome(decision_trace_category, "gave_up_after_retries", caller_name, f"final status {response.status_code}")
            return response

        delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
        _logger.warning(
            "%s: attempt %d/%d to %s got retryable status %d -- retrying in %.1fs.",
            caller_name, attempt, max_attempts, url, response.status_code, delay,
        )
        sleep_fn(delay)

    # Unreachable in practice (the loop always returns/raises on its last
    # iteration above), but keeps type-checkers honest about a fallthrough.
    if last_exc is not None:
        raise last_exc
    assert last_response is not None
    return last_response


def _record_outcome(category: str, decision: str, backend: str, reason: str) -> None:
    decision_trace_log.log(category, decision, backend, reason=reason)
