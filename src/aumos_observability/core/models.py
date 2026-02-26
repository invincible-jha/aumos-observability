"""SQLAlchemy ORM models for the Observability Stack.

Table prefix: obs_
All tenant-scoped tables extend AumOSModel.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aumos_common.database import AumOSModel


class SLODefinition(AumOSModel):
    """SLO definition stored in PostgreSQL.

    Burn rate calculations are evaluated against Prometheus and cached here.
    The SLO engine reads these definitions on a configurable interval to
    compute error budget consumption and fire multi-window burn rate alerts.
    """

    __tablename__ = "obs_slo_definitions"

    # Basic metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    slo_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Target
    target_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # PromQL queries
    numerator_query: Mapped[str] = mapped_column(Text, nullable=False)
    denominator_query: Mapped[str] = mapped_column(Text, nullable=False)

    # Window configuration
    window_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # Burn rate thresholds
    fast_burn_threshold: Mapped[float] = mapped_column(Float, default=14.4, nullable=False)
    slow_burn_threshold: Mapped[float] = mapped_column(Float, default=6.0, nullable=False)

    # Labels as JSONB for flexible alert routing
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)

    # Cached burn rate (updated by SLO engine background task)
    cached_fast_burn_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    cached_slow_burn_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    cached_error_budget_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)


class AlertRule(AumOSModel):
    """Custom alert rule definition.

    Stores tenant-specific Prometheus alert rules. These are synced to
    Prometheus rule files on change via the AlertService.
    """

    __tablename__ = "obs_alert_rules"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # PromQL expression
    expr: Mapped[str] = mapped_column(Text, nullable=False)
    for_duration: Mapped[str] = mapped_column(String(20), default="5m", nullable=False)

    # Metadata
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Routing — list of Alertmanager receiver names
    notification_channels: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AlertHistory(AumOSModel):
    """Historical record of a fired alert.

    Immutable audit log of when alerts fired and resolved.
    Linked to an AlertRule by UUID (no FK constraint — cross-service safe).
    """

    __tablename__ = "obs_alert_history"

    alert_rule_id: Mapped[Any] = mapped_column(nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False)  # firing | resolved
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Dashboard(AumOSModel):
    """Dashboard provisioning metadata record.

    Tracks which dashboards have been provisioned to Grafana per tenant.
    The full JSON payload lives in Grafana; this is a lightweight registry.
    """

    __tablename__ = "obs_dashboards"

    uid: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    folder_name: Mapped[str] = mapped_column(String(255), default="AumOS", nullable=False)
    grafana_url: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_bundled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SLOBudget(AumOSModel):
    """Point-in-time SLO error budget snapshot.

    Stores periodic burn rate calculations from the SLO engine
    for historical trending on the SLO dashboards.
    """

    __tablename__ = "obs_slo_budgets"

    slo_id: Mapped[Any] = mapped_column(nullable=False, index=True)
    fast_burn_rate: Mapped[float] = mapped_column(Float, nullable=False)
    slow_burn_rate: Mapped[float] = mapped_column(Float, nullable=False)
    error_budget_minutes_remaining: Mapped[float] = mapped_column(Float, nullable=False)
    error_budget_consumed_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    is_fast_burning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_slow_burning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
