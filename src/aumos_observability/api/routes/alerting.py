"""Correlated alert ingestion and group query endpoints.

Provides four endpoints that integrate with the AlertCorrelationEngine:

- POST /api/v1/alerts/ingest      — receive an alert, return correlation result
- GET  /api/v1/alerts/groups      — list active correlated alert groups
- GET  /api/v1/alerts/groups/{id} — fetch a specific group with root cause
- GET  /api/v1/alerts/statistics  — correlation engine stats

The engine instance is a module-level singleton initialised once at import
time. All state is held in-memory with a 60-second rolling window.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from aumos_common.observability import get_logger

from aumos_observability.core.alerting.correlation_engine import (
    Alert,
    AlertCorrelationEngine,
    AlertSeverity,
    CorrelatedAlertGroup,
)

logger = get_logger(__name__)

# Module-level singleton — shared across all requests in this process.
_engine: AlertCorrelationEngine = AlertCorrelationEngine(window_seconds=60)

router = APIRouter(prefix="/alerts", tags=["Alert Correlation"])


# ─────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────


class AlertIngestRequest(BaseModel):
    """Payload for ingesting a single alert into the correlation engine."""

    service_name: str = Field(
        min_length=1,
        max_length=255,
        description="Name of the AumOS service emitting the alert",
    )
    tenant_id: str = Field(
        min_length=1,
        max_length=255,
        description="Tenant identifier for isolation",
    )
    severity: AlertSeverity = Field(description="Alert severity level")
    message: str = Field(
        min_length=1,
        max_length=2000,
        description="Human-readable alert description",
    )
    timestamp: datetime | None = Field(
        default=None,
        description="UTC alert timestamp; defaults to server time if omitted",
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key/value labels for routing and filtering",
    )


class AlertResponse(BaseModel):
    """Serialised representation of a single Alert."""

    id: str
    service_name: str
    tenant_id: str
    severity: AlertSeverity
    message: str
    timestamp: datetime
    labels: dict[str, str]
    is_root_cause: bool
    correlated_group_id: str | None


class CorrelatedGroupResponse(BaseModel):
    """Serialised representation of a CorrelatedAlertGroup."""

    group_id: str
    tenant_id: str
    started_at: datetime
    suppressed_count: int
    root_cause: AlertResponse | None
    related_alerts: list[AlertResponse]


class AlertIngestResponse(BaseModel):
    """Response from the alert ingestion endpoint."""

    suppressed: bool = Field(
        description="True when the alert was suppressed as a child of an existing root-cause group",
    )
    group: CorrelatedGroupResponse | None = Field(
        description="The correlated group this alert belongs to, or None if suppressed",
    )


class CorrelationStatisticsResponse(BaseModel):
    """Current correlation engine statistics."""

    active_groups: int = Field(description="Number of active correlation groups")
    buffered_alerts: int = Field(description="Number of alerts in the rolling buffer")
    total_suppressed: int = Field(description="Total suppressed child alerts across all groups")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _alert_to_response(alert: Alert) -> AlertResponse:
    """Map a domain Alert dataclass to an AlertResponse schema."""
    return AlertResponse(
        id=alert.id,
        service_name=alert.service_name,
        tenant_id=alert.tenant_id,
        severity=alert.severity,
        message=alert.message,
        timestamp=alert.timestamp,
        labels=alert.labels,
        is_root_cause=alert.is_root_cause,
        correlated_group_id=alert.correlated_group_id,
    )


def _group_to_response(group: CorrelatedAlertGroup) -> CorrelatedGroupResponse:
    """Map a domain CorrelatedAlertGroup dataclass to a CorrelatedGroupResponse schema."""
    return CorrelatedGroupResponse(
        group_id=group.group_id,
        tenant_id=group.tenant_id,
        started_at=group.started_at,
        suppressed_count=group.suppressed_count,
        root_cause=_alert_to_response(group.root_cause) if group.root_cause else None,
        related_alerts=[_alert_to_response(a) for a in group.related_alerts],
    )


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────


@router.post(
    "/ingest",
    response_model=AlertIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest alert and return correlation result",
)
async def ingest_alert(request: AlertIngestRequest) -> AlertIngestResponse:
    """Ingest a single alert and run it through the correlation engine.

    The engine checks whether the alert is a child of an existing root-cause
    group (in which case it is suppressed and ``suppressed=True`` is returned)
    or whether it creates a new correlated group.

    Args:
        request: Alert payload.

    Returns:
        AlertIngestResponse indicating whether the alert was suppressed and
        which group it belongs to.
    """
    alert = Alert(
        service_name=request.service_name,
        tenant_id=request.tenant_id,
        severity=request.severity,
        message=request.message,
        timestamp=request.timestamp or datetime.now(timezone.utc),
        labels=request.labels,
    )

    logger.info(
        "alert_ingest_received",
        service_name=alert.service_name,
        tenant_id=alert.tenant_id,
        severity=alert.severity.value,
    )

    group = await _engine.ingest_alert(alert)

    if group is None:
        return AlertIngestResponse(suppressed=True, group=None)

    return AlertIngestResponse(suppressed=False, group=_group_to_response(group))


@router.get(
    "/groups",
    response_model=list[CorrelatedGroupResponse],
    summary="List active correlated alert groups",
)
async def list_alert_groups() -> list[CorrelatedGroupResponse]:
    """Return all currently active alert correlation groups.

    Groups are pruned automatically after 2× the correlation window (120 seconds
    by default), so this list reflects only recent incidents.

    Returns:
        List of active CorrelatedGroupResponse objects.
    """
    groups = _engine.get_active_groups()
    logger.info("alert_groups_listed", count=len(groups))
    return [_group_to_response(g) for g in groups]


@router.get(
    "/groups/{group_id}",
    response_model=CorrelatedGroupResponse,
    summary="Get a specific correlated alert group",
)
async def get_alert_group(group_id: str) -> CorrelatedGroupResponse:
    """Retrieve a specific correlated alert group by its UUID.

    Args:
        group_id: UUID string of the target group.

    Returns:
        CorrelatedGroupResponse with root cause and related alerts.

    Raises:
        HTTPException 404: If the group does not exist or has expired.
    """
    group = _engine.get_group(group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Correlation group '{group_id}' not found or has expired",
        )
    logger.info("alert_group_fetched", group_id=group_id)
    return _group_to_response(group)


@router.get(
    "/statistics",
    response_model=CorrelationStatisticsResponse,
    summary="Correlation engine statistics",
)
async def get_correlation_statistics() -> CorrelationStatisticsResponse:
    """Return current state statistics for the alert correlation engine.

    Returns:
        CorrelationStatisticsResponse with active group count, buffer size,
        and total suppressed alert count.
    """
    stats = _engine.get_statistics()
    return CorrelationStatisticsResponse(**stats)
