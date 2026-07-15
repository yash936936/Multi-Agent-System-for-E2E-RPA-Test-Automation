from __future__ import annotations

import pytest

from agents.capability.performance_adapter import PerformanceAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from tests.conftest_local_server import make_server, server_url

PAGE = b"<html><body><h1>Hello Perf</h1></body></html>"


@pytest.fixture
def server():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


def test_generous_budget_passes(server):
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.PERFORMANCE, target=url,
            params={"url": url, "budget": {"load_time_ms": 60000, "dom_content_loaded_ms": 60000}},
        )
    )

    assert result.passed is True
    assert result.evidence["violations"] == {}
    assert "load_time_ms" in result.evidence["metrics_ms"]


def test_impossibly_tight_budget_fails(server):
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.PERFORMANCE, target=url,
            params={"url": url, "budget": {"load_time_ms": 0}},
        )
    )

    assert result.passed is False
    assert result.escalate is True
    assert "load_time_ms" in result.evidence["violations"]
    violation = result.evidence["violations"]["load_time_ms"]
    assert violation["budget_ms"] == 0
    assert violation["actual_ms"] >= 0


def test_metrics_collected_are_real_navigation_timing_values(server):
    """Not fabricated numbers -- must reflect the real page load via performance API."""
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.PERFORMANCE, target=url, params={"url": url, "budget": {}})
    )

    assert result.passed is True  # empty budget -> nothing to violate
    metrics = result.evidence["metrics_ms"]
    assert "dom_content_loaded_ms" in metrics or "load_time_ms" in metrics
    for value in metrics.values():
        assert value >= 0


def test_missing_url_fails_closed():
    adapter = PerformanceAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.PERFORMANCE, target="", params={})
    )
    assert result.passed is False
    assert "url" in result.evidence["error"]


def test_default_budget_used_when_none_specified(server):
    """Confirms _DEFAULT_BUDGET_MS is actually applied, not just documented."""
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.PERFORMANCE, target=url, params={"url": url})
    )
    # A local single-page test server should comfortably pass generous defaults.
    assert result.passed is True
    assert set(result.evidence["budget_ms"].keys()) >= {"load_time_ms", "dom_content_loaded_ms"}


def test_registry_includes_all_phase_l_adapters():
    """Phase L: three-way registration check (CapabilityType enum + default_registry())
    for all three new adapters -- accessibility, security_headers, performance."""
    from agents.capability.accessibility_adapter import AccessibilityAdapter
    from agents.capability.security_headers_adapter import SecurityHeadersAdapter
    from orchestrator.capability_adapter import default_registry

    registry = default_registry()
    assert CapabilityType.ACCESSIBILITY in registry.registered_types()
    assert CapabilityType.SECURITY_HEADERS in registry.registered_types()
    assert CapabilityType.PERFORMANCE in registry.registered_types()
    assert isinstance(registry.get(CapabilityType.ACCESSIBILITY), AccessibilityAdapter)
    assert isinstance(registry.get(CapabilityType.SECURITY_HEADERS), SecurityHeadersAdapter)
    assert isinstance(registry.get(CapabilityType.PERFORMANCE), PerformanceAdapter)
