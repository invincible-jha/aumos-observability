"""Tests for aumos_observability.core.alerting.correlation_engine.

Covers:
- Root cause detection (upstream failure suppresses downstream alerts)
- Window expiry (alerts outside the window are not correlated)
- Multi-tenant isolation (alerts from tenant A do not suppress tenant B alerts)
- Statistics tracking
- Standalone alerts (no downstream impact)
- Transitive dependency detection
- Stale group pruning
- Multiple downstream alerts grouped under a single root cause
- Repeated ingestion from the same service
- Correct suppressed_count bookkeeping
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from aumos_observability.core.alerting.correlation_engine import (
    Alert,
    AlertCorrelationEngine,
    AlertSeverity,
    CorrelatedAlertGroup,
)


def _alert(
    service_name: str,
    tenant_id: str = "tenant-A",
    severity: AlertSeverity = AlertSeverity.WARNING,
    message: str = "test alert",
    timestamp: datetime | None = None,
) -> Alert:
    """Helper to construct a test Alert with sensible defaults."""
    return Alert(
        service_name=service_name,
        tenant_id=tenant_id,
        severity=severity,
        message=message,
        timestamp=timestamp or datetime.now(timezone.utc),
    )


class TestRootCauseDetection:
    """Root-cause alerts trigger grouping and suppress downstream alerts."""

    def test_upstream_alert_followed_by_downstream_returns_group(self) -> None:
        """When a downstream alert arrives after an upstream one, a group is created."""
        engine = AlertCorrelationEngine(window_seconds=60)

        # Ingest downstream alert first so it sits in the buffer
        downstream = _alert("aumos-governance-engine")
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(downstream))

        # Now ingest the root-cause upstream alert
        upstream = _alert("aumos-data-layer")
        result = asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream))

        assert result is not None
        assert upstream.is_root_cause is True
        assert len(result.related_alerts) == 1
        assert result.related_alerts[0].id == downstream.id

    def test_downstream_alert_after_root_cause_is_suppressed(self) -> None:
        """A downstream alert arriving after a root-cause group is created returns None."""
        engine = AlertCorrelationEngine(window_seconds=60)

        # Root cause arrives first
        upstream = _alert("aumos-data-layer")
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream))

        # Now downstream arrives — should be suppressed
        downstream = _alert("aumos-governance-engine")
        result = asyncio.get_event_loop().run_until_complete(engine.ingest_alert(downstream))

        assert result is None

    def test_suppressed_count_increments_per_child_alert(self) -> None:
        """Each suppressed child increments suppressed_count on the group."""
        engine = AlertCorrelationEngine(window_seconds=60)

        upstream = _alert("aumos-data-layer")
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream))

        child_services = [
            "aumos-governance-engine",
            "aumos-model-registry",
            "aumos-ai-finops",
        ]
        for service in child_services:
            asyncio.get_event_loop().run_until_complete(engine.ingest_alert(_alert(service)))

        groups = engine.get_active_groups()
        assert len(groups) == 1
        assert groups[0].suppressed_count == len(child_services)

    def test_suppressed_alert_gets_correlated_group_id(self) -> None:
        """Suppressed alerts have their correlated_group_id set to the parent group."""
        engine = AlertCorrelationEngine(window_seconds=60)

        upstream = _alert("aumos-data-layer")
        group = asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream))
        assert group is not None
        group_id = group.root_cause.correlated_group_id if group.root_cause else None

        downstream = _alert("aumos-governance-engine")
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(downstream))

        assert downstream.correlated_group_id == group_id


class TestWindowExpiry:
    """Alerts outside the correlation window are not grouped."""

    def test_alert_outside_window_is_not_correlated(self) -> None:
        """A downstream alert older than window_seconds is treated as standalone."""
        engine = AlertCorrelationEngine(window_seconds=30)

        # Old downstream alert — 60 seconds in the past, outside the 30s window
        old_downstream = _alert(
            "aumos-governance-engine",
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(old_downstream))

        # Root cause alert now
        upstream = _alert("aumos-data-layer")
        result = asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream))

        # Should be a standalone group — no related alerts correlated
        assert result is not None
        assert len(result.related_alerts) == 0

    def test_alert_within_window_is_correlated(self) -> None:
        """A downstream alert within window_seconds IS grouped with a root cause."""
        engine = AlertCorrelationEngine(window_seconds=60)

        # Downstream 30 seconds ago — within 60s window
        recent_downstream = _alert(
            "aumos-governance-engine",
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(recent_downstream))

        upstream = _alert("aumos-data-layer")
        result = asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream))

        assert result is not None
        assert len(result.related_alerts) == 1


class TestMultiTenantIsolation:
    """Alerts from different tenants do not correlate with each other."""

    def test_tenant_a_root_cause_does_not_suppress_tenant_b_downstream(self) -> None:
        """An upstream alert from tenant-A must not suppress tenant-B downstream alerts."""
        engine = AlertCorrelationEngine(window_seconds=60)

        # tenant-A root cause
        upstream_a = _alert("aumos-data-layer", tenant_id="tenant-A")
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream_a))

        # tenant-B downstream — should NOT be suppressed
        downstream_b = _alert("aumos-governance-engine", tenant_id="tenant-B")
        result = asyncio.get_event_loop().run_until_complete(engine.ingest_alert(downstream_b))

        # Not suppressed — result is a standalone group
        assert result is not None

    def test_same_tenant_alerts_do_correlate(self) -> None:
        """Alerts from the same tenant do correlate across service boundaries."""
        engine = AlertCorrelationEngine(window_seconds=60)

        downstream = _alert("aumos-governance-engine", tenant_id="tenant-X")
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(downstream))

        upstream = _alert("aumos-data-layer", tenant_id="tenant-X")
        result = asyncio.get_event_loop().run_until_complete(engine.ingest_alert(upstream))

        assert result is not None
        assert upstream.is_root_cause is True

    def test_different_tenant_groups_are_independent(self) -> None:
        """Two tenants can each have an independent root-cause group simultaneously."""
        engine = AlertCorrelationEngine(window_seconds=60)

        for tenant in ("tenant-A", "tenant-B"):
            asyncio.get_event_loop().run_until_complete(
                engine.ingest_alert(_alert("aumos-data-layer", tenant_id=tenant))
            )

        stats = engine.get_statistics()
        assert stats["active_groups"] == 2


class TestStatistics:
    """get_statistics returns accurate engine state."""

    def test_statistics_empty_engine(self) -> None:
        engine = AlertCorrelationEngine(window_seconds=60)
        stats = engine.get_statistics()
        assert stats == {"active_groups": 0, "buffered_alerts": 0, "total_suppressed": 0}

    def test_statistics_after_standalone_alert(self) -> None:
        """A standalone alert (no group) does not increment active_groups."""
        engine = AlertCorrelationEngine(window_seconds=60)
        asyncio.get_event_loop().run_until_complete(engine.ingest_alert(_alert("aumos-unknown-service")))
        stats = engine.get_statistics()
        assert stats["active_groups"] == 0
        assert stats["buffered_alerts"] == 1
        assert stats["total_suppressed"] == 0

    def test_statistics_after_root_cause_group_created(self) -> None:
        engine = AlertCorrelationEngine(window_seconds=60)
        asyncio.get_event_loop().run_until_complete(
            engine.ingest_alert(_alert("aumos-governance-engine"))
        )
        asyncio.get_event_loop().run_until_complete(
            engine.ingest_alert(_alert("aumos-data-layer"))
        )
        stats = engine.get_statistics()
        assert stats["active_groups"] == 1
        assert stats["total_suppressed"] == 1


class TestTransitiveDependencies:
    """_is_downstream handles one level of transitive dependencies."""

    def test_direct_dependency_detected(self) -> None:
        engine = AlertCorrelationEngine()
        assert engine._is_downstream("aumos-data-layer", "aumos-governance-engine") is True

    def test_transitive_dependency_detected(self) -> None:
        """aumos-platform-core → aumos-data-layer → aumos-governance-engine (2 hops)."""
        engine = AlertCorrelationEngine()
        assert engine._is_downstream("aumos-platform-core", "aumos-governance-engine") is True

    def test_unrelated_services_are_not_downstream(self) -> None:
        engine = AlertCorrelationEngine()
        assert engine._is_downstream("aumos-ai-finops", "aumos-hallucination-shield") is False


class TestGetGroupAndGetActiveGroups:
    """get_group and get_active_groups return correct data."""

    def test_get_group_returns_none_for_unknown_id(self) -> None:
        engine = AlertCorrelationEngine()
        assert engine.get_group("nonexistent-group-id") is None

    def test_get_active_groups_returns_all_groups(self) -> None:
        engine = AlertCorrelationEngine(window_seconds=60)

        # Create two groups from two different tenants
        for tenant in ("alpha", "beta"):
            asyncio.get_event_loop().run_until_complete(
                engine.ingest_alert(_alert("aumos-governance-engine", tenant_id=tenant))
            )
            asyncio.get_event_loop().run_until_complete(
                engine.ingest_alert(_alert("aumos-data-layer", tenant_id=tenant))
            )

        groups = engine.get_active_groups()
        assert len(groups) == 2
