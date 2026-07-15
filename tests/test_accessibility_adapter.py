from __future__ import annotations

import pytest

from agents.capability.accessibility_adapter import AccessibilityAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from tests.conftest_local_server import make_server, server_url

BROKEN_PAGE = b"""
<html><body>
  <img src="x.png">
  <a href="#"></a>
</body></html>
"""

CLEAN_PAGE = b"""
<html lang="en"><head><title>Test Page</title></head>
<body><main><h1>Hello</h1><img src="x.png" alt="A test image"><a href="/about">About</a></main></body></html>
"""


@pytest.fixture
def broken_server():
    srv = make_server(BROKEN_PAGE)
    yield srv
    srv.shutdown()


@pytest.fixture
def clean_server():
    srv = make_server(CLEAN_PAGE)
    yield srv
    srv.shutdown()


def test_deliberately_broken_page_fails_with_real_axe_violations(broken_server):
    """Verified against a deliberately-broken local HTML fixture, per the Phase L1 plan."""
    adapter = AccessibilityAdapter()
    url = server_url(broken_server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.ACCESSIBILITY, target=url, params={"url": url})
    )

    assert result.passed is False
    assert result.escalate is True
    assert result.evidence["total_violations"] > 0
    violation_ids = {v["id"] for v in result.evidence["violations"]}
    assert "image-alt" in violation_ids  # img with no alt text -- reliably flagged as "critical"


def test_clean_page_passes(clean_server):
    adapter = AccessibilityAdapter()
    url = server_url(clean_server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.ACCESSIBILITY, target=url, params={"url": url})
    )

    assert result.passed is True
    assert result.evidence["total_violations"] == 0


def test_severity_threshold_filters_lower_impact_violations(broken_server):
    """
    With severity_threshold='critical', only the image-alt violation
    (impact=critical) should cause a failure -- the moderate/serious ones
    present on the same broken page shouldn't count against this threshold.
    """
    adapter = AccessibilityAdapter()
    url = server_url(broken_server)
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.ACCESSIBILITY, target=url,
            params={"url": url, "severity_threshold": "critical"},
        )
    )

    assert result.passed is False  # image-alt (critical) still qualifies
    assert result.evidence["qualifying_violation_count"] >= 1
    assert result.evidence["total_violations"] > result.evidence["qualifying_violation_count"]


def test_invalid_severity_threshold_fails_closed():
    adapter = AccessibilityAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.ACCESSIBILITY, target="https://example.com",
            params={"url": "https://example.com", "severity_threshold": "not_a_real_level"},
        )
    )
    assert result.passed is False
    assert "severity_threshold" in result.evidence["error"]


def test_missing_url_fails_closed():
    adapter = AccessibilityAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.ACCESSIBILITY, target="", params={})
    )
    assert result.passed is False
    assert "url" in result.evidence["error"]


def test_vendored_axe_core_actually_exists_on_disk():
    """Sanity check that the vendored file this adapter depends on is really there."""
    from agents.capability.accessibility_adapter import _AXE_CORE_PATH

    assert _AXE_CORE_PATH.exists()
    assert _AXE_CORE_PATH.stat().st_size > 100_000  # the real minified bundle, not a stub
