"""Pydantic request/response schemas for the Observability API."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────


class SLOType(str, Enum):
    """Type of SLO."""

    AVAILABILITY = "availability"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"
    CUSTOM = "custom"


class SLOStatus(str, Enum):
    """Current SLO compliance status."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertState(str, Enum):
    """Alert states."""

    FIRING = "firing"
    RESOLVED = "resolved"
    PENDING = "pending"


# ─────────────────────────────────────────────
# SLO Schemas
# ─────────────────────────────────────────────


class SLOCreateRequest(BaseModel):
    """Request body for creating a new SLO definition."""

    name: str = Field(min_length=1, max_length=255, description="Human-readable SLO name")
    description: str = Field(default="", max_length=1000, description="SLO description")
    slo_type: SLOType = Field(description="Type of SLO metric")
    target_percentage: float = Field(ge=0.0, le=100.0, description="Target SLO percentage (e.g. 99.9)")
    service_name: str = Field(min_length=1, max_length=255, description="Target service name")
    numerator_query: str = Field(min_length=1, description="PromQL numerator query (good events)")
    denominator_query: str = Field(min_length=1, description="PromQL denominator query (total events)")
    window_days: int = Field(default=30, ge=1, le=365, description="Rolling window in days")
    fast_burn_threshold: float = Field(
        default=14.4,
        ge=1.0,
        description="Fast burn rate threshold multiplier (5-min window)",
    )
    slow_burn_threshold: float = Field(
        default=6.0,
        ge=1.0,
        description="Slow burn rate threshold multiplier (1-hr window)",
    )
    labels: dict[str, str] = Field(default_factory=dict, description="Additional labels for alert routing")


class SLOUpdateRequest(BaseModel):
    """Request body for updating an existing SLO definition."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    target_percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    fast_burn_threshold: float | None = Field(default=None, ge=1.0)
    slow_burn_threshold: float | None = Field(default=None, ge=1.0)
    labels: dict[str, str] | None = None
    is_active: bool | None = None


class SLOBurnRateResponse(BaseModel):
    """Current burn rate calculation result."""

    slo_id: uuid.UUID
    current_error_budget_minutes: float = Field(description="Remaining error budget in minutes")
    total_error_budget_minutes: float = Field(description="Total error budget for window in minutes")
    error_budget_consumed_percentage: float = Field(description="Percentage of error budget consumed")
    fast_burn_rate: float = Field(description="Current burn rate over fast window")
    slow_burn_rate: float = Field(description="Current burn rate over slow window")
    is_fast_burning: bool = Field(description="True if fast burn alert should fire")
    is_slow_burning: bool = Field(description="True if slow burn alert should fire")
    calculated_at: datetime


class SLOResponse(BaseModel):
    """SLO definition response."""

    id: uuid.UUID
    tenant_id: str
    name: str
    description: str
    slo_type: SLOType
    target_percentage: float
    service_name: str
    numerator_query: str
    denominator_query: str
    window_days: int
    fast_burn_threshold: float
    slow_burn_threshold: float
    labels: dict[str, str]
    is_active: bool
    status: SLOStatus
    burn_rate: SLOBurnRateResponse | None
    created_at: datetime
    updated_at: datetime


class SLOListResponse(BaseModel):
    """Paginated list of SLOs."""

    items: list[SLOResponse]
    total: int
    page: int
    page_size: int


# ─────────────────────────────────────────────
# Alert Rule Schemas
# ─────────────────────────────────────────────


class AlertRuleCreateRequest(BaseModel):
    """Request body for creating an alert rule."""

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    severity: AlertSeverity
    expr: str = Field(min_length=1, description="PromQL alert expression")
    for_duration: str = Field(default="5m", description="Duration condition must be true before firing")
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    notification_channels: list[str] = Field(
        default_factory=list,
        description="Alertmanager receiver names",
    )


class AlertRuleUpdateRequest(BaseModel):
    """Request body for updating an alert rule."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    severity: AlertSeverity | None = None
    expr: str | None = None
    for_duration: str | None = None
    labels: dict[str, str] | None = None
    annotations: dict[str, str] | None = None
    notification_channels: list[str] | None = None
    is_active: bool | None = None


class AlertRuleResponse(BaseModel):
    """Alert rule response."""

    id: uuid.UUID
    tenant_id: str
    name: str
    description: str
    severity: AlertSeverity
    expr: str
    for_duration: str
    labels: dict[str, str]
    annotations: dict[str, str]
    notification_channels: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AlertRuleListResponse(BaseModel):
    """Paginated list of alert rules."""

    items: list[AlertRuleResponse]
    total: int
    page: int
    page_size: int


class ActiveAlertResponse(BaseModel):
    """An active alert from Alertmanager."""

    fingerprint: str
    labels: dict[str, str]
    annotations: dict[str, str]
    state: AlertState
    starts_at: datetime
    ends_at: datetime | None
    generator_url: str


# ─────────────────────────────────────────────
# Dashboard Schemas
# ─────────────────────────────────────────────


class DashboardProvisionRequest(BaseModel):
    """Request to provision a dashboard to Grafana."""

    dashboard_name: str = Field(min_length=1, max_length=255)
    folder_name: str = Field(default="AumOS", description="Grafana folder to place dashboard in")
    overwrite: bool = Field(default=True, description="Overwrite if dashboard already exists")
    dashboard_json: dict[str, Any] = Field(description="Full Grafana dashboard JSON payload")


class DashboardResponse(BaseModel):
    """Dashboard provisioning result."""

    uid: str
    slug: str
    url: str
    status: str
    version: int


class DashboardListResponse(BaseModel):
    """List of provisioned dashboards."""

    items: list[DashboardResponse]
    total: int


# ─────────────────────────────────────────────
# Metrics Query Schemas
# ─────────────────────────────────────────────


class MetricsQueryRequest(BaseModel):
    """Ad-hoc Prometheus metrics query."""

    query: str = Field(min_length=1, description="PromQL query")
    start: datetime | None = Field(default=None, description="Range start (omit for instant query)")
    end: datetime | None = Field(default=None, description="Range end (omit for instant query)")
    step: str = Field(default="60s", description="Step interval for range queries")


class MetricsSample(BaseModel):
    """A single metric sample."""

    metric: dict[str, str]
    values: list[tuple[float, str]]


class MetricsQueryResponse(BaseModel):
    """Prometheus query result."""

    result_type: str
    result: list[MetricsSample]
    query: str
    execution_time_ms: float
