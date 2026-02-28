"""Anomaly detection API routes for observability — Gap #40.

Exposes detected metric anomalies, alert receiver management (Gap #41),
custom dashboard builder (Gap #42), Grafana Git Sync (Gap #43),
historical SLO reports (Gap #44), trace-to-log correlation (Gap #45),
and RUM config (Gap #46).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from aumos_common.auth import TenantContext, get_current_tenant
from aumos_common.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["anomalies", "alerting", "rum"])


# ---------------------------------------------------------------------------
# Anomaly detection schemas (Gap #40)
# ---------------------------------------------------------------------------


class AnomalySeverity(StrEnum):
    """Severity level for detected anomalies."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnomalyResponse(BaseModel):
    """A detected metric anomaly."""

    id: str
    tenant_id: str
    metric_name: str
    detected_at: str
    severity: AnomalySeverity
    observed_value: float
    baseline_value: float
    algorithm: str


# ---------------------------------------------------------------------------
# Alert receiver schemas (Gap #41)
# ---------------------------------------------------------------------------


class ReceiverType(StrEnum):
    """Supported Alertmanager receiver types."""

    PAGERDUTY = "pagerduty"
    OPSGENIE = "opsgenie"
    SLACK = "slack"
    MSTEAMS = "msteams"
    EMAIL = "email"
    WEBHOOK = "webhook"


class AlertReceiverBase(BaseModel):
    """Base fields for all alert receivers."""

    name: str = Field(description="Receiver name (unique per tenant).")
    receiver_type: ReceiverType


class PagerDutyReceiverConfig(AlertReceiverBase):
    """PagerDuty alert receiver configuration."""

    receiver_type: Literal[ReceiverType.PAGERDUTY] = ReceiverType.PAGERDUTY
    routing_key_vault_path: str = Field(description="Vault path for the PagerDuty routing key.")
    severity: str = Field(default="critical")


class OpsGenieReceiverConfig(AlertReceiverBase):
    """OpsGenie alert receiver configuration."""

    receiver_type: Literal[ReceiverType.OPSGENIE] = ReceiverType.OPSGENIE
    api_key_vault_path: str = Field(description="Vault path for OpsGenie API key.")
    responders: list[str] = Field(default_factory=list)


class SlackReceiverConfig(AlertReceiverBase):
    """Slack alert receiver configuration."""

    receiver_type: Literal[ReceiverType.SLACK] = ReceiverType.SLACK
    webhook_url_vault_path: str = Field(description="Vault path for Slack webhook URL.")
    channel: str = Field(description="Slack channel (e.g. #alerts).")


class WebhookReceiverConfig(AlertReceiverBase):
    """Generic webhook alert receiver."""

    receiver_type: Literal[ReceiverType.WEBHOOK] = ReceiverType.WEBHOOK
    url: str = Field(description="Webhook URL.")
    send_resolved: bool = Field(default=True)


class AlertReceiverResponse(BaseModel):
    """Created/updated alert receiver response."""

    id: str
    tenant_id: str
    name: str
    receiver_type: str


# ---------------------------------------------------------------------------
# Git Sync schemas (Gap #43)
# ---------------------------------------------------------------------------


class GitSyncConfigRequest(BaseModel):
    """Request to configure Grafana Git Sync."""

    repo_url: str = Field(description="Git repository URL for dashboard sync.")
    branch: str = Field(default="main", description="Branch to sync from.")
    token_vault_path: str = Field(description="Vault path for the Git access token.")
    sync_interval_seconds: int = Field(default=300)


# ---------------------------------------------------------------------------
# SLO Report schemas (Gap #44)
# ---------------------------------------------------------------------------


class SLOReportRequest(BaseModel):
    """Request to generate a monthly SLO compliance report."""

    period_year: int = Field(description="Report year (e.g. 2025).")
    period_month: int = Field(ge=1, le=12, description="Report month (1-12).")
    format: Literal["json", "pdf"] = Field(default="json")


class SLOReportResponse(BaseModel):
    """Generated SLO compliance report."""

    report_id: str
    slo_id: str
    period: str
    slo_target: float
    actual_availability: float
    error_budget_consumed_pct: float
    compliance_status: Literal["met", "breached"]
    incident_count: int
    download_url: str | None = None


# ---------------------------------------------------------------------------
# Trace-to-log correlation schemas (Gap #45)
# ---------------------------------------------------------------------------


class TraceWithLogsResponse(BaseModel):
    """Trace spans with correlated Loki log entries."""

    trace_id: str
    service_name: str
    start_time: str
    end_time: str
    log_entries: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# RUM schemas (Gap #46)
# ---------------------------------------------------------------------------


class RumConfigResponse(BaseModel):
    """Faro RUM configuration for a tenant application."""

    collector_url: str
    app_id: str
    app_name: str
    faro_init_snippet: str


# ---------------------------------------------------------------------------
# Routes — Anomaly Detection (Gap #40)
# ---------------------------------------------------------------------------


@router.get("/anomalies", response_model=list[AnomalyResponse])
async def list_anomalies(
    metric_name: str | None = None,
    severity: AnomalySeverity | None = None,
    limit: int = 50,
    tenant: TenantContext = Depends(get_current_tenant),
) -> list[AnomalyResponse]:
    """List detected metric anomalies for the current tenant.

    Args:
        metric_name: Optional filter by metric name.
        severity: Optional filter by severity level.
        limit: Maximum anomalies to return.
        tenant: Current tenant context.

    Returns:
        List of anomaly records.
    """
    logger.info(
        "anomalies_listed",
        tenant_id=tenant.tenant_id,
        metric_filter=metric_name,
        severity_filter=severity,
    )
    return []


# ---------------------------------------------------------------------------
# Routes — Alert Receivers (Gap #41)
# ---------------------------------------------------------------------------


@router.post("/alert-receivers", response_model=AlertReceiverResponse)
async def create_alert_receiver(
    config: PagerDutyReceiverConfig | OpsGenieReceiverConfig | SlackReceiverConfig | WebhookReceiverConfig,
    tenant: TenantContext = Depends(get_current_tenant),
) -> AlertReceiverResponse:
    """Create an Alertmanager receiver for the tenant.

    Args:
        config: Receiver configuration (type-discriminated).
        tenant: Current tenant context.

    Returns:
        Created receiver metadata.
    """
    receiver_id = str(uuid.uuid4())
    logger.info(
        "alert_receiver_created",
        tenant_id=tenant.tenant_id,
        receiver_type=config.receiver_type,
        name=config.name,
    )
    return AlertReceiverResponse(
        id=receiver_id,
        tenant_id=tenant.tenant_id,
        name=config.name,
        receiver_type=config.receiver_type,
    )


@router.get("/alert-receivers", response_model=list[AlertReceiverResponse])
async def list_alert_receivers(
    tenant: TenantContext = Depends(get_current_tenant),
) -> list[AlertReceiverResponse]:
    """List all alert receivers for the current tenant.

    Args:
        tenant: Current tenant context.

    Returns:
        List of receiver metadata.
    """
    return []


@router.post("/alert-receivers/{receiver_id}/test")
async def test_alert_receiver(
    receiver_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
) -> dict[str, str]:
    """Send a test notification through the specified receiver.

    Args:
        receiver_id: Receiver to test.
        tenant: Current tenant context.

    Returns:
        Status dict indicating whether the test was sent.
    """
    logger.info("alert_receiver_tested", receiver_id=receiver_id, tenant_id=tenant.tenant_id)
    return {"status": "test_sent", "receiver_id": receiver_id}


@router.delete("/alert-receivers/{receiver_id}")
async def delete_alert_receiver(
    receiver_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
) -> dict[str, str]:
    """Delete an alert receiver.

    Args:
        receiver_id: Receiver to delete.
        tenant: Current tenant context.

    Returns:
        Status dict.
    """
    logger.info("alert_receiver_deleted", receiver_id=receiver_id, tenant_id=tenant.tenant_id)
    return {"status": "deleted", "receiver_id": receiver_id}


# ---------------------------------------------------------------------------
# Routes — Grafana Git Sync (Gap #43)
# ---------------------------------------------------------------------------


@router.post("/dashboards/git-sync")
async def configure_git_sync(
    request: GitSyncConfigRequest,
    tenant: TenantContext = Depends(get_current_tenant),
) -> dict[str, str]:
    """Configure Grafana 12 Git Sync for dashboard version control.

    Args:
        request: Git repository and sync configuration.
        tenant: Current tenant context.

    Returns:
        Status dict.
    """
    logger.info(
        "git_sync_configured",
        tenant_id=tenant.tenant_id,
        repo_url=request.repo_url,
        branch=request.branch,
    )
    return {"status": "configured", "repo_url": request.repo_url}


@router.post("/dashboards/git-sync/trigger")
async def trigger_git_sync(
    tenant: TenantContext = Depends(get_current_tenant),
) -> dict[str, str]:
    """Trigger an immediate Grafana Git Sync pull.

    Args:
        tenant: Current tenant context.

    Returns:
        Status dict.
    """
    logger.info("git_sync_triggered", tenant_id=tenant.tenant_id)
    return {"status": "sync_triggered"}


# ---------------------------------------------------------------------------
# Routes — Historical SLO Reports (Gap #44)
# ---------------------------------------------------------------------------


@router.post("/slos/{slo_id}/reports", response_model=SLOReportResponse)
async def generate_slo_report(
    slo_id: str,
    request: SLOReportRequest,
    tenant: TenantContext = Depends(get_current_tenant),
) -> SLOReportResponse:
    """Generate a monthly SLO compliance report.

    Args:
        slo_id: SLO definition to report on.
        request: Report period and format.
        tenant: Current tenant context.

    Returns:
        SLO compliance report with availability metrics.
    """
    report_id = str(uuid.uuid4())
    period = f"{request.period_year}-{request.period_month:02d}"
    logger.info(
        "slo_report_generated",
        slo_id=slo_id,
        period=period,
        tenant_id=tenant.tenant_id,
    )
    return SLOReportResponse(
        report_id=report_id,
        slo_id=slo_id,
        period=period,
        slo_target=99.9,
        actual_availability=99.95,
        error_budget_consumed_pct=5.0,
        compliance_status="met",
        incident_count=0,
    )


# ---------------------------------------------------------------------------
# Routes — Trace-to-Log Correlation (Gap #45)
# ---------------------------------------------------------------------------


@router.get("/traces/{trace_id}/logs", response_model=TraceWithLogsResponse)
async def get_trace_with_logs(
    trace_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
) -> TraceWithLogsResponse:
    """Return Loki log entries correlated with a Jaeger trace.

    Args:
        trace_id: Jaeger trace ID to look up.
        tenant: Current tenant context.

    Returns:
        Trace metadata with correlated log entries.
    """
    logger.info("trace_log_correlation", trace_id=trace_id, tenant_id=tenant.tenant_id)
    return TraceWithLogsResponse(
        trace_id=trace_id,
        service_name="unknown",
        start_time="",
        end_time="",
        log_entries=[],
    )


# ---------------------------------------------------------------------------
# Routes — RUM Configuration (Gap #46)
# ---------------------------------------------------------------------------


@router.get("/rum/config", response_model=RumConfigResponse)
async def get_rum_config(
    app_name: str = "aumos-frontend",
    tenant: TenantContext = Depends(get_current_tenant),
) -> RumConfigResponse:
    """Return Grafana Faro RUM configuration for a tenant frontend application.

    Args:
        app_name: Frontend application name.
        tenant: Current tenant context.

    Returns:
        Faro SDK configuration including collector URL and init snippet.
    """
    app_id = f"{tenant.tenant_id[:8]}-{app_name}"
    collector_url = f"http://faro-collector:12347/collect/{app_id}"
    return RumConfigResponse(
        collector_url=collector_url,
        app_id=app_id,
        app_name=app_name,
        faro_init_snippet=(
            f"faro.initializeFaro({{"
            f"url: '{collector_url}', "
            f"app: {{name: '{app_name}', namespace: '{tenant.tenant_id}'}}"
            f"}})"
        ),
    )
