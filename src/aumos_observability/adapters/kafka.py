"""Kafka event publisher for the Observability Stack.

Publishes audit and observability domain events to the AumOS event bus.
Extends the base EventPublisher from aumos-common with observability-specific
helper methods for common event types.
"""

from __future__ import annotations

from typing import Any

from aumos_common.events import EventPublisher, Topics
from aumos_common.observability import get_logger

logger = get_logger(__name__)


class ObservabilityEventPublisher:
    """Publishes observability domain events to Kafka.

    Wraps aumos_common.EventPublisher with typed helpers for:
    - SLO lifecycle events (created, updated, deleted, status_changed)
    - Alert rule lifecycle events (created, fired, resolved)
    - Dashboard provisioning events
    - Burn rate threshold events

    All events are published to Topics.OBSERVABILITY_EVENTS.
    """

    def __init__(self, publisher: EventPublisher) -> None:
        """Initialise with the base event publisher from aumos-common.

        Args:
            publisher: Configured Kafka event publisher.
        """
        self._publisher = publisher

    async def publish_slo_created(
        self,
        tenant_id: str,
        slo_id: str,
        slo_name: str,
        service_name: str,
        target_percentage: float,
    ) -> None:
        """Publish an SLO created event.

        Args:
            tenant_id: Tenant that owns the SLO.
            slo_id: UUID string of the new SLO.
            slo_name: Human-readable SLO name.
            service_name: Target service for the SLO.
            target_percentage: SLO target (e.g. 99.9).
        """
        await self._publish(
            "slo_created",
            tenant_id=tenant_id,
            slo_id=slo_id,
            slo_name=slo_name,
            service_name=service_name,
            target_percentage=target_percentage,
        )
        logger.info("Published slo_created event", slo_id=slo_id)

    async def publish_slo_status_changed(
        self,
        tenant_id: str,
        slo_id: str,
        slo_name: str,
        previous_status: str,
        new_status: str,
        fast_burn_rate: float,
        slow_burn_rate: float,
    ) -> None:
        """Publish an SLO status change event (e.g. ok -> critical).

        Args:
            tenant_id: Tenant that owns the SLO.
            slo_id: SLO UUID string.
            slo_name: Human-readable SLO name.
            previous_status: Previous SLO status string.
            new_status: New SLO status string.
            fast_burn_rate: Current fast burn rate.
            slow_burn_rate: Current slow burn rate.
        """
        await self._publish(
            "slo_status_changed",
            tenant_id=tenant_id,
            slo_id=slo_id,
            slo_name=slo_name,
            previous_status=previous_status,
            new_status=new_status,
            fast_burn_rate=fast_burn_rate,
            slow_burn_rate=slow_burn_rate,
        )
        logger.info(
            "Published slo_status_changed event",
            slo_id=slo_id,
            previous_status=previous_status,
            new_status=new_status,
        )

    async def publish_slo_deleted(
        self,
        tenant_id: str,
        slo_id: str,
        slo_name: str,
    ) -> None:
        """Publish an SLO deleted event.

        Args:
            tenant_id: Tenant that owns the SLO.
            slo_id: SLO UUID string.
            slo_name: Human-readable SLO name.
        """
        await self._publish(
            "slo_deleted",
            tenant_id=tenant_id,
            slo_id=slo_id,
            slo_name=slo_name,
        )
        logger.info("Published slo_deleted event", slo_id=slo_id)

    async def publish_alert_rule_created(
        self,
        tenant_id: str,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> None:
        """Publish an alert rule created event.

        Args:
            tenant_id: Tenant that owns the alert rule.
            rule_id: UUID string of the new alert rule.
            rule_name: Human-readable rule name.
            severity: Rule severity level (critical, warning, info).
        """
        await self._publish(
            "alert_rule_created",
            tenant_id=tenant_id,
            rule_id=rule_id,
            rule_name=rule_name,
            severity=severity,
        )
        logger.info("Published alert_rule_created event", rule_id=rule_id)

    async def publish_alert_fired(
        self,
        tenant_id: str,
        rule_id: str,
        rule_name: str,
        severity: str,
        labels: dict[str, str],
        annotations: dict[str, str],
    ) -> None:
        """Publish an alert fired event.

        Args:
            tenant_id: Tenant whose alert fired.
            rule_id: UUID string of the alert rule.
            rule_name: Human-readable rule name.
            severity: Alert severity level.
            labels: Prometheus labels on the alert.
            annotations: Alert annotations (summary, description, runbook).
        """
        await self._publish(
            "alert_fired",
            tenant_id=tenant_id,
            rule_id=rule_id,
            rule_name=rule_name,
            severity=severity,
            labels=labels,
            annotations=annotations,
        )
        logger.warning(
            "Published alert_fired event",
            rule_id=rule_id,
            severity=severity,
        )

    async def publish_alert_resolved(
        self,
        tenant_id: str,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> None:
        """Publish an alert resolved event.

        Args:
            tenant_id: Tenant whose alert resolved.
            rule_id: UUID string of the alert rule.
            rule_name: Human-readable rule name.
            severity: Alert severity level.
        """
        await self._publish(
            "alert_resolved",
            tenant_id=tenant_id,
            rule_id=rule_id,
            rule_name=rule_name,
            severity=severity,
        )
        logger.info("Published alert_resolved event", rule_id=rule_id)

    async def publish_dashboard_provisioned(
        self,
        tenant_id: str,
        dashboard_uid: str,
        dashboard_name: str,
        grafana_url: str,
    ) -> None:
        """Publish a dashboard provisioned event.

        Args:
            tenant_id: Tenant for whom the dashboard was provisioned.
            dashboard_uid: Grafana dashboard UID.
            dashboard_name: Human-readable dashboard name.
            grafana_url: Full Grafana URL to the dashboard.
        """
        await self._publish(
            "dashboard_provisioned",
            tenant_id=tenant_id,
            dashboard_uid=dashboard_uid,
            dashboard_name=dashboard_name,
            grafana_url=grafana_url,
        )
        logger.info("Published dashboard_provisioned event", dashboard_uid=dashboard_uid)

    async def _publish(self, event_type: str, **kwargs: Any) -> None:
        """Publish a typed event to the observability events topic.

        Args:
            event_type: String event type identifier.
            **kwargs: Additional fields to include in the event payload.
        """
        payload: dict[str, Any] = {"event_type": event_type, **kwargs}
        await self._publisher.publish(Topics.OBSERVABILITY_EVENTS, payload)
