"""Observability Cost Tracking adapter.

Tracks per-tenant observability costs: metric cardinality, log volume,
trace storage, and generates optimization recommendations and cost reports.
Enforces budget limits with alerting when thresholds are exceeded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class CostComponentType(str, Enum):
    """Observability cost component categories."""

    METRICS_CARDINALITY = "metrics_cardinality"
    LOG_VOLUME = "log_volume"
    TRACE_STORAGE = "trace_storage"
    ALERT_EVALUATIONS = "alert_evaluations"
    DASHBOARD_QUERIES = "dashboard_queries"


class OptimizationType(str, Enum):
    """Type of cost optimization recommendation."""

    REDUCE_CARDINALITY = "reduce_cardinality"
    INCREASE_SAMPLING = "increase_sampling"
    AGGREGATE_METRICS = "aggregate_metrics"
    REDUCE_LOG_VERBOSITY = "reduce_log_verbosity"
    ENABLE_RECORDING_RULES = "enable_recording_rules"
    ARCHIVE_OLD_DATA = "archive_old_data"


@dataclass
class TenantCostSummary:
    """Per-tenant observability cost breakdown.

    Attributes:
        tenant_id: Tenant identifier.
        metric_series_count: Active Prometheus time series count.
        metric_cardinality_cost_usd: Estimated monthly cost for metrics.
        log_bytes_per_day: Average daily log ingestion in bytes.
        log_cost_usd: Estimated monthly cost for log storage.
        trace_spans_per_day: Average daily trace span count.
        trace_cost_usd: Estimated monthly cost for trace storage.
        total_cost_usd: Total estimated monthly observability cost.
        budget_limit_usd: Monthly budget limit (None if unlimited).
        budget_utilization_pct: Fraction of budget consumed (0–100).
        computed_at: UTC timestamp of cost computation.
    """

    tenant_id: str
    metric_series_count: int
    metric_cardinality_cost_usd: float
    log_bytes_per_day: float
    log_cost_usd: float
    trace_spans_per_day: float
    trace_cost_usd: float
    total_cost_usd: float
    budget_limit_usd: float | None
    budget_utilization_pct: float
    computed_at: datetime


@dataclass
class CostTrendPoint:
    """Single point in a cost trend time series.

    Attributes:
        timestamp: UTC timestamp of the measurement.
        cost_usd: Observed cost at this point.
        component: Cost component category.
    """

    timestamp: datetime
    cost_usd: float
    component: CostComponentType


@dataclass
class OptimizationRecommendation:
    """A cost optimization recommendation.

    Attributes:
        optimization_type: Category of optimization.
        description: Human-readable explanation.
        estimated_savings_usd: Estimated monthly savings if applied.
        priority: Priority score 1 (low) to 5 (critical).
        affected_component: The cost component this targets.
        action_detail: Specific action to take.
    """

    optimization_type: OptimizationType
    description: str
    estimated_savings_usd: float
    priority: int
    affected_component: CostComponentType
    action_detail: str


@dataclass
class CostReport:
    """Complete observability cost report for a tenant.

    Attributes:
        tenant_id: Tenant identifier.
        report_period_days: Number of days covered.
        summary: Current cost summary.
        trend: Time series of cost measurements.
        recommendations: Ordered list of optimization recommendations.
        budget_alert_fired: True if budget limit was exceeded.
        generated_at: UTC timestamp of report generation.
    """

    tenant_id: str
    report_period_days: int
    summary: TenantCostSummary
    trend: list[CostTrendPoint]
    recommendations: list[OptimizationRecommendation]
    budget_alert_fired: bool
    generated_at: datetime


# Approximate cost constants — adjust for deployment environment
_METRIC_SERIES_COST_PER_1K_USD = 0.20  # per 1,000 active series per month
_LOG_COST_PER_GB_USD = 0.10  # per GB per month
_TRACE_SPAN_COST_PER_1M_USD = 0.05  # per 1M spans per month
_HIGH_CARDINALITY_THRESHOLD = 100_000  # series count triggering recommendation
_HIGH_LOG_VOLUME_THRESHOLD_GB = 50.0  # daily GB triggering recommendation


class ObservabilityCostTracker:
    """Observability cost management adapter.

    Queries Prometheus for metric cardinality data, estimates costs for
    log and trace storage, generates optimization recommendations,
    and enforces budget limits with alerting.

    Args:
        prometheus_client: Async Prometheus HTTP API client.
        loki_client: Optional Loki API client for log volume queries.
        metric_series_cost_per_1k: Cost per 1,000 active metric series per month.
        log_cost_per_gb: Cost per GB of log storage per month.
        trace_span_cost_per_1m: Cost per 1M trace spans per month.
    """

    def __init__(
        self,
        prometheus_client: Any,
        loki_client: Any | None = None,
        metric_series_cost_per_1k: float = _METRIC_SERIES_COST_PER_1K_USD,
        log_cost_per_gb: float = _LOG_COST_PER_GB_USD,
        trace_span_cost_per_1m: float = _TRACE_SPAN_COST_PER_1M_USD,
    ) -> None:
        """Initialize ObservabilityCostTracker.

        Args:
            prometheus_client: Async Prometheus HTTP API client.
            loki_client: Optional Loki API client for log volume queries.
            metric_series_cost_per_1k: Monthly cost per 1K active series.
            log_cost_per_gb: Monthly cost per GB of log storage.
            trace_span_cost_per_1m: Monthly cost per 1M trace spans.
        """
        self._prometheus = prometheus_client
        self._loki = loki_client
        self._metric_series_cost_per_1k = metric_series_cost_per_1k
        self._log_cost_per_gb = log_cost_per_gb
        self._trace_span_cost_per_1m = trace_span_cost_per_1m

    async def get_metric_cardinality(self, tenant_id: str) -> int:
        """Query Prometheus for active time series count for a tenant.

        Uses the Prometheus TSDB stats endpoint to get the total count
        of active series filtered by tenant_id label.

        Args:
            tenant_id: Tenant identifier (must match Prometheus label value).

        Returns:
            Count of active Prometheus time series for the tenant.
        """
        try:
            query = f'count({{tenant_id="{tenant_id}"}})'
            result = await self._prometheus.instant_query(query)
            data = result.get("data", {}).get("result", [])
            if data:
                return int(float(data[0].get("value", [0, 0])[1]))
        except Exception as exc:
            logger.warning(
                "Failed to query metric cardinality",
                tenant_id=tenant_id,
                error=str(exc),
            )
        return 0

    async def get_log_volume_bytes_per_day(self, tenant_id: str) -> float:
        """Estimate average daily log ingestion volume for a tenant.

        Queries Prometheus for the Loki ingest rate metric if available,
        otherwise falls back to Loki query API.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Estimated log bytes ingested per day.
        """
        try:
            query = f'sum(rate(loki_ingester_bytes_received_total{{tenant="{tenant_id}"}}[24h])) * 86400'
            result = await self._prometheus.instant_query(query)
            data = result.get("data", {}).get("result", [])
            if data:
                return float(data[0].get("value", [0, 0])[1])
        except Exception as exc:
            logger.warning(
                "Failed to query log volume",
                tenant_id=tenant_id,
                error=str(exc),
            )
        return 0.0

    async def get_trace_spans_per_day(self, tenant_id: str) -> float:
        """Estimate average daily trace span count for a tenant.

        Queries Prometheus for OTEL span ingestion rate metrics.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Estimated trace spans per day.
        """
        try:
            query = (
                f'sum(rate(traces_exporter_sent_spans_total{{tenant_id="{tenant_id}"}}[24h])) * 86400'
            )
            result = await self._prometheus.instant_query(query)
            data = result.get("data", {}).get("result", [])
            if data:
                return float(data[0].get("value", [0, 0])[1])
        except Exception as exc:
            logger.warning(
                "Failed to query trace spans",
                tenant_id=tenant_id,
                error=str(exc),
            )
        return 0.0

    def _compute_cost_usd(
        self,
        series_count: int,
        log_bytes_per_day: float,
        trace_spans_per_day: float,
    ) -> tuple[float, float, float]:
        """Compute USD cost estimates for each observability component.

        Args:
            series_count: Active Prometheus time series count.
            log_bytes_per_day: Daily log ingestion in bytes.
            trace_spans_per_day: Daily trace span count.

        Returns:
            Tuple of (metric_cost, log_cost, trace_cost) in USD/month.
        """
        metric_cost = (series_count / 1000.0) * self._metric_series_cost_per_1k
        log_gb_per_month = (log_bytes_per_day / (1024**3)) * 30
        log_cost = log_gb_per_month * self._log_cost_per_gb
        trace_cost = (trace_spans_per_day / 1_000_000.0) * 30 * self._trace_span_cost_per_1m
        return metric_cost, log_cost, trace_cost

    def _generate_recommendations(
        self,
        series_count: int,
        log_bytes_per_day: float,
        trace_spans_per_day: float,
        budget_utilization_pct: float,
    ) -> list[OptimizationRecommendation]:
        """Generate cost optimization recommendations based on observed usage.

        Args:
            series_count: Active Prometheus time series count.
            log_bytes_per_day: Daily log ingestion in bytes.
            trace_spans_per_day: Daily trace span count.
            budget_utilization_pct: Current budget utilization percentage.

        Returns:
            Ordered list of recommendations by priority (descending).
        """
        recommendations: list[OptimizationRecommendation] = []

        if series_count > _HIGH_CARDINALITY_THRESHOLD:
            excess_series = series_count - _HIGH_CARDINALITY_THRESHOLD
            savings = (excess_series / 1000.0) * self._metric_series_cost_per_1k
            recommendations.append(
                OptimizationRecommendation(
                    optimization_type=OptimizationType.REDUCE_CARDINALITY,
                    description=(
                        f"Metric cardinality is {series_count:,} active series. "
                        f"Audit label dimensions and remove high-cardinality labels like "
                        f"request_id, user_id, or session_id from metric labels."
                    ),
                    estimated_savings_usd=savings,
                    priority=4,
                    affected_component=CostComponentType.METRICS_CARDINALITY,
                    action_detail="Use relabeling rules in Prometheus scrape config to drop high-cardinality labels.",
                )
            )

        if series_count > 10_000:
            recommendations.append(
                OptimizationRecommendation(
                    optimization_type=OptimizationType.ENABLE_RECORDING_RULES,
                    description=(
                        "Enable Prometheus recording rules to pre-aggregate expensive queries "
                        "and reduce query-time computation."
                    ),
                    estimated_savings_usd=series_count * 0.00002,
                    priority=3,
                    affected_component=CostComponentType.METRICS_CARDINALITY,
                    action_detail="Create recording rules for frequently-queried rate/aggregation expressions.",
                )
            )

        log_gb_per_day = log_bytes_per_day / (1024**3)
        if log_gb_per_day > _HIGH_LOG_VOLUME_THRESHOLD_GB:
            savings = (log_gb_per_day - _HIGH_LOG_VOLUME_THRESHOLD_GB) * 30 * self._log_cost_per_gb
            recommendations.append(
                OptimizationRecommendation(
                    optimization_type=OptimizationType.REDUCE_LOG_VERBOSITY,
                    description=(
                        f"Log volume is {log_gb_per_day:.1f} GB/day. "
                        f"Review log levels and disable DEBUG logging in production."
                    ),
                    estimated_savings_usd=savings,
                    priority=3,
                    affected_component=CostComponentType.LOG_VOLUME,
                    action_detail="Set log level to INFO in all services and use sampling for DEBUG logs.",
                )
            )

        if trace_spans_per_day > 10_000_000:
            recommendations.append(
                OptimizationRecommendation(
                    optimization_type=OptimizationType.INCREASE_SAMPLING,
                    description=(
                        f"Trace volume is {trace_spans_per_day:,.0f} spans/day. "
                        f"Increase head-based sampling rate to reduce storage costs."
                    ),
                    estimated_savings_usd=(trace_spans_per_day / 1_000_000.0) * 0.5 * self._trace_span_cost_per_1m,
                    priority=3,
                    affected_component=CostComponentType.TRACE_STORAGE,
                    action_detail="Configure OTEL Collector with probabilistic sampler at 10% for non-error spans.",
                )
            )

        if budget_utilization_pct > 80.0:
            recommendations.append(
                OptimizationRecommendation(
                    optimization_type=OptimizationType.ARCHIVE_OLD_DATA,
                    description=(
                        f"Budget utilization is at {budget_utilization_pct:.1f}%. "
                        f"Archive data older than 30 days to cold storage."
                    ),
                    estimated_savings_usd=0.0,
                    priority=5,
                    affected_component=CostComponentType.LOG_VOLUME,
                    action_detail="Configure Loki and Thanos retention policies to expire data after 30 days.",
                )
            )

        return sorted(recommendations, key=lambda r: r.priority, reverse=True)

    async def compute_tenant_cost(
        self,
        tenant_id: str,
        budget_limit_usd: float | None = None,
    ) -> TenantCostSummary:
        """Compute the current observability cost summary for a tenant.

        Args:
            tenant_id: Tenant identifier.
            budget_limit_usd: Monthly budget cap in USD (None for unlimited).

        Returns:
            TenantCostSummary with component breakdown and budget utilization.
        """
        series_count = await self.get_metric_cardinality(tenant_id)
        log_bytes_per_day = await self.get_log_volume_bytes_per_day(tenant_id)
        trace_spans_per_day = await self.get_trace_spans_per_day(tenant_id)

        metric_cost, log_cost, trace_cost = self._compute_cost_usd(
            series_count=series_count,
            log_bytes_per_day=log_bytes_per_day,
            trace_spans_per_day=trace_spans_per_day,
        )
        total_cost = metric_cost + log_cost + trace_cost

        budget_utilization_pct = 0.0
        if budget_limit_usd and budget_limit_usd > 0:
            budget_utilization_pct = min((total_cost / budget_limit_usd) * 100.0, 100.0)

        logger.info(
            "Tenant observability cost computed",
            tenant_id=tenant_id,
            total_cost_usd=total_cost,
            series_count=series_count,
            budget_utilization_pct=budget_utilization_pct,
        )

        return TenantCostSummary(
            tenant_id=tenant_id,
            metric_series_count=series_count,
            metric_cardinality_cost_usd=metric_cost,
            log_bytes_per_day=log_bytes_per_day,
            log_cost_usd=log_cost,
            trace_spans_per_day=trace_spans_per_day,
            trace_cost_usd=trace_cost,
            total_cost_usd=total_cost,
            budget_limit_usd=budget_limit_usd,
            budget_utilization_pct=budget_utilization_pct,
            computed_at=datetime.now(tz=timezone.utc),
        )

    async def generate_cost_report(
        self,
        tenant_id: str,
        report_period_days: int = 30,
        budget_limit_usd: float | None = None,
    ) -> CostReport:
        """Generate a full observability cost report for a tenant.

        Includes current cost summary, trend analysis, optimization
        recommendations, and budget alert status.

        Args:
            tenant_id: Tenant identifier.
            report_period_days: Days to include in the report period.
            budget_limit_usd: Monthly budget limit for alerting.

        Returns:
            CostReport with summary, trends, and recommendations.
        """
        summary = await self.compute_tenant_cost(
            tenant_id=tenant_id,
            budget_limit_usd=budget_limit_usd,
        )

        trend = await self._build_trend(
            tenant_id=tenant_id,
            period_days=report_period_days,
        )

        recommendations = self._generate_recommendations(
            series_count=summary.metric_series_count,
            log_bytes_per_day=summary.log_bytes_per_day,
            trace_spans_per_day=summary.trace_spans_per_day,
            budget_utilization_pct=summary.budget_utilization_pct,
        )

        budget_alert_fired = (
            budget_limit_usd is not None and summary.total_cost_usd > budget_limit_usd
        )

        if budget_alert_fired:
            logger.warning(
                "Observability budget exceeded",
                tenant_id=tenant_id,
                total_cost_usd=summary.total_cost_usd,
                budget_limit_usd=budget_limit_usd,
            )

        return CostReport(
            tenant_id=tenant_id,
            report_period_days=report_period_days,
            summary=summary,
            trend=trend,
            recommendations=recommendations,
            budget_alert_fired=budget_alert_fired,
            generated_at=datetime.now(tz=timezone.utc),
        )

    async def _build_trend(
        self,
        tenant_id: str,
        period_days: int,
    ) -> list[CostTrendPoint]:
        """Build a cost trend by sampling daily Prometheus range data.

        Queries Prometheus for metric cardinality over the period and
        converts to estimated daily cost points.

        Args:
            tenant_id: Tenant identifier.
            period_days: Number of days to include in the trend.

        Returns:
            List of CostTrendPoint entries, one per day.
        """
        trend_points: list[CostTrendPoint] = []
        now = time.time()
        start = now - (period_days * 86400)

        try:
            query = f'count({{tenant_id="{tenant_id}"}})'
            result = await self._prometheus.range_query(
                query=query,
                start=start,
                end=now,
                step="1d",
            )
            data = result.get("data", {}).get("result", [])
            if data:
                for ts_value in data[0].get("values", []):
                    ts = float(ts_value[0])
                    series_ct = int(float(ts_value[1]))
                    metric_cost, _, _ = self._compute_cost_usd(
                        series_count=series_ct,
                        log_bytes_per_day=0.0,
                        trace_spans_per_day=0.0,
                    )
                    trend_points.append(
                        CostTrendPoint(
                            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                            cost_usd=metric_cost,
                            component=CostComponentType.METRICS_CARDINALITY,
                        )
                    )
        except Exception as exc:
            logger.warning(
                "Failed to build cost trend",
                tenant_id=tenant_id,
                error=str(exc),
            )

        return trend_points

    async def check_budget_enforcement(
        self,
        tenant_id: str,
        budget_limit_usd: float,
    ) -> bool:
        """Check whether a tenant has exceeded their observability budget.

        Args:
            tenant_id: Tenant identifier.
            budget_limit_usd: Monthly budget limit in USD.

        Returns:
            True if the tenant is over budget and an alert should fire.
        """
        summary = await self.compute_tenant_cost(
            tenant_id=tenant_id,
            budget_limit_usd=budget_limit_usd,
        )
        return summary.total_cost_usd > budget_limit_usd


__all__ = [
    "CostComponentType",
    "CostReport",
    "CostTrendPoint",
    "ObservabilityCostTracker",
    "OptimizationRecommendation",
    "OptimizationType",
    "TenantCostSummary",
]
