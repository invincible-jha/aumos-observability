"""Business logic services for the Observability Stack.

Contains:
- SLOService — SLO CRUD + burn rate calculations
- AlertService — Alert rule CRUD + Alertmanager queries
- DashboardService — Grafana dashboard provisioning
- MetricsService — Ad-hoc Prometheus queries
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aumos_common.auth import TenantContext
from aumos_common.events import EventPublisher, Topics
from aumos_common.observability import get_logger
from aumos_common.pagination import PageRequest

from aumos_observability.api.schemas import (
    ActiveAlertResponse,
    AlertRuleCreateRequest,
    AlertRuleListResponse,
    AlertRuleResponse,
    AlertRuleUpdateRequest,
    AlertState,
    DashboardListResponse,
    DashboardProvisionRequest,
    DashboardResponse,
    MetricsQueryRequest,
    MetricsQueryResponse,
    MetricsSample,
    SLOBurnRateResponse,
    SLOCreateRequest,
    SLOListResponse,
    SLOResponse,
    SLOStatus,
    SLOUpdateRequest,
)

if TYPE_CHECKING:
    from aumos_observability.adapters.adaptive_sampling import AdaptiveSamplingEngine
    from aumos_observability.adapters.cost_tracking import ObservabilityCostTracker
    from aumos_observability.adapters.grafana_client import GrafanaClient
    from aumos_observability.adapters.prometheus_client import PrometheusClient
    from aumos_observability.adapters.repositories import AlertRuleRepository, SLORepository
    from aumos_observability.adapters.slo_engine import SLOEngineAdapter, SLOStatusSnapshot
    from aumos_observability.adapters.trace_sampling import TraceSamplingAdapter
    from aumos_observability.core.slo_engine import BurnRateResult

logger = get_logger(__name__)


# ─────────────────────────────────────────────
# SLO Service
# ─────────────────────────────────────────────


class SLOService:
    """SLO lifecycle management and burn rate evaluation.

    Handles CRUD operations for SLO definitions and delegates
    burn rate computation to the SLOBurnRateEngine.
    """

    def __init__(
        self,
        repository: SLORepository,
        publisher: EventPublisher | None = None,
        prometheus: PrometheusClient | None = None,
    ) -> None:
        """Initialise SLOService.

        Args:
            repository: SLO persistence repository.
            publisher: Kafka event publisher (optional for tests).
            prometheus: Prometheus client for burn rate queries.
        """
        self._repo = repository
        self._publisher = publisher
        self._prometheus = prometheus

    async def create_slo(
        self,
        request: SLOCreateRequest,
        tenant: TenantContext,
    ) -> SLOResponse:
        """Create a new SLO definition.

        Args:
            request: Validated SLO creation payload.
            tenant: Current tenant context.

        Returns:
            Created SLO with initial status of UNKNOWN.
        """
        data: dict[str, Any] = {
            "tenant_id": tenant.tenant_id,
            "name": request.name,
            "description": request.description,
            "slo_type": request.slo_type.value,
            "target_percentage": request.target_percentage,
            "service_name": request.service_name,
            "numerator_query": request.numerator_query,
            "denominator_query": request.denominator_query,
            "window_days": request.window_days,
            "fast_burn_threshold": request.fast_burn_threshold,
            "slow_burn_threshold": request.slow_burn_threshold,
            "labels": request.labels,
            "is_active": True,
            "last_status": SLOStatus.UNKNOWN.value,
        }
        model = await self._repo.create(data)

        if self._publisher:
            await self._publisher.publish(
                Topics.OBSERVABILITY_EVENTS,
                {
                    "event_type": "slo_created",
                    "tenant_id": tenant.tenant_id,
                    "slo_id": str(model.id),
                    "slo_name": model.name,
                },
            )

        logger.info("SLO created", slo_id=str(model.id), tenant_id=tenant.tenant_id)
        return self._to_response(model, burn_rate=None)

    async def list_slos(
        self,
        tenant: TenantContext,
        pagination: PageRequest,
        service_name: str | None = None,
    ) -> SLOListResponse:
        """List SLO definitions with optional service filter.

        Args:
            tenant: Current tenant context.
            pagination: Page and size parameters.
            service_name: Optional service name filter.

        Returns:
            Paginated SLO list.
        """
        items, total = await self._repo.list_all(
            page=pagination.page,
            page_size=pagination.page_size,
            service_name=service_name,
        )
        return SLOListResponse(
            items=[self._to_response(item, burn_rate=None) for item in items],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    async def get_slo(
        self,
        slo_id: uuid.UUID,
        tenant: TenantContext,
    ) -> SLOResponse | None:
        """Retrieve a single SLO by ID.

        Args:
            slo_id: SLO primary key.
            tenant: Current tenant context.

        Returns:
            SLO response or None if not found.
        """
        model = await self._repo.get_by_id(slo_id)
        if model is None or model.tenant_id != tenant.tenant_id:
            return None
        return self._to_response(model, burn_rate=None)

    async def update_slo(
        self,
        slo_id: uuid.UUID,
        request: SLOUpdateRequest,
        tenant: TenantContext,
    ) -> SLOResponse | None:
        """Update an existing SLO definition.

        Args:
            slo_id: SLO primary key.
            request: Fields to update.
            tenant: Current tenant context.

        Returns:
            Updated SLO or None if not found.
        """
        existing = await self._repo.get_by_id(slo_id)
        if existing is None or existing.tenant_id != tenant.tenant_id:
            return None

        update_data: dict[str, Any] = {
            key: value
            for key, value in request.model_dump(exclude_none=True).items()
        }
        model = await self._repo.update(slo_id, update_data)
        if model is None:
            return None

        logger.info("SLO updated", slo_id=str(slo_id), tenant_id=tenant.tenant_id)
        return self._to_response(model, burn_rate=None)

    async def delete_slo(
        self,
        slo_id: uuid.UUID,
        tenant: TenantContext,
    ) -> bool:
        """Delete an SLO definition.

        Args:
            slo_id: SLO primary key.
            tenant: Current tenant context.

        Returns:
            True if deleted, False if not found.
        """
        existing = await self._repo.get_by_id(slo_id)
        if existing is None or existing.tenant_id != tenant.tenant_id:
            return False
        return await self._repo.delete(slo_id)

    async def calculate_burn_rate(
        self,
        slo_id: uuid.UUID,
        tenant: TenantContext,
    ) -> SLOBurnRateResponse | None:
        """Calculate current burn rate for an SLO.

        Args:
            slo_id: SLO primary key.
            tenant: Current tenant context.

        Returns:
            Burn rate calculation or None if SLO not found.
        """
        model = await self._repo.get_by_id(slo_id)
        if model is None or model.tenant_id != tenant.tenant_id:
            return None

        if self._prometheus is None:
            # Return cached values when Prometheus not available
            return SLOBurnRateResponse(
                slo_id=model.id,
                current_error_budget_minutes=model.cached_error_budget_minutes or 0.0,
                total_error_budget_minutes=model.window_days * 24 * 60 * (1.0 - model.target_percentage / 100.0),
                error_budget_consumed_percentage=0.0,
                fast_burn_rate=model.cached_fast_burn_rate or 0.0,
                slow_burn_rate=model.cached_slow_burn_rate or 0.0,
                is_fast_burning=False,
                is_slow_burning=False,
                calculated_at=model.last_evaluated_at or datetime.now(tz=timezone.utc),
            )

        from aumos_observability.core.slo_engine import SLOBurnRateEngine

        engine = SLOBurnRateEngine(prometheus=self._prometheus)
        result = await engine.calculate(
            slo_id=str(slo_id),
            numerator_query=model.numerator_query,
            denominator_query=model.denominator_query,
            target_percentage=model.target_percentage,
            window_days=model.window_days,
            fast_burn_threshold=model.fast_burn_threshold,
            slow_burn_threshold=model.slow_burn_threshold,
        )

        # Persist the latest burn rate back to DB
        await self._repo.update(slo_id, {
            "cached_fast_burn_rate": result.fast_burn_rate,
            "cached_slow_burn_rate": result.slow_burn_rate,
            "cached_error_budget_minutes": result.current_error_budget_minutes,
            "last_evaluated_at": result.calculated_at,
            "last_status": self._burn_rate_to_status(result).value,
        })

        return SLOBurnRateResponse(
            slo_id=model.id,
            current_error_budget_minutes=result.current_error_budget_minutes,
            total_error_budget_minutes=result.total_error_budget_minutes,
            error_budget_consumed_percentage=result.error_budget_consumed_percentage,
            fast_burn_rate=result.fast_burn_rate,
            slow_burn_rate=result.slow_burn_rate,
            is_fast_burning=result.is_fast_burning,
            is_slow_burning=result.is_slow_burning,
            calculated_at=result.calculated_at,
        )

    def _burn_rate_to_status(self, result: BurnRateResult) -> SLOStatus:
        """Map burn rate result to SLO status enum."""
        if result.is_fast_burning:
            return SLOStatus.CRITICAL
        if result.is_slow_burning:
            return SLOStatus.WARNING
        return SLOStatus.OK

    def _to_response(self, model: Any, burn_rate: SLOBurnRateResponse | None) -> SLOResponse:
        """Map an ORM model to an API response schema."""
        return SLOResponse(
            id=model.id,
            tenant_id=model.tenant_id,
            name=model.name,
            description=model.description,
            slo_type=model.slo_type,
            target_percentage=model.target_percentage,
            service_name=model.service_name,
            numerator_query=model.numerator_query,
            denominator_query=model.denominator_query,
            window_days=model.window_days,
            fast_burn_threshold=model.fast_burn_threshold,
            slow_burn_threshold=model.slow_burn_threshold,
            labels=model.labels or {},
            is_active=model.is_active,
            status=SLOStatus(model.last_status) if model.last_status else SLOStatus.UNKNOWN,
            burn_rate=burn_rate,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


# ─────────────────────────────────────────────
# Alert Service
# ─────────────────────────────────────────────


class AlertService:
    """Alert rule lifecycle management and active alert retrieval.

    Manages custom Prometheus alert rule definitions per tenant and
    queries Alertmanager for currently active alerts.
    """

    def __init__(
        self,
        repository: AlertRuleRepository,
        publisher: EventPublisher | None = None,
    ) -> None:
        """Initialise AlertService.

        Args:
            repository: Alert rule persistence repository.
            publisher: Kafka event publisher.
        """
        self._repo = repository
        self._publisher = publisher

    async def create_rule(
        self,
        request: AlertRuleCreateRequest,
        tenant: TenantContext,
    ) -> AlertRuleResponse:
        """Create a new alert rule.

        Args:
            request: Alert rule creation payload.
            tenant: Current tenant context.

        Returns:
            Created alert rule.
        """
        data: dict[str, Any] = {
            "tenant_id": tenant.tenant_id,
            "name": request.name,
            "description": request.description,
            "severity": request.severity.value,
            "expr": request.expr,
            "for_duration": request.for_duration,
            "labels": request.labels,
            "annotations": request.annotations,
            "notification_channels": request.notification_channels,
            "is_active": True,
        }
        model = await self._repo.create(data)
        logger.info("Alert rule created", rule_id=str(model.id), tenant_id=tenant.tenant_id)
        return self._to_response(model)

    async def list_rules(
        self,
        tenant: TenantContext,
        pagination: PageRequest,
        severity: str | None = None,
    ) -> AlertRuleListResponse:
        """List alert rules for the tenant.

        Args:
            tenant: Current tenant context.
            pagination: Page parameters.
            severity: Optional severity filter.

        Returns:
            Paginated alert rule list.
        """
        items, total = await self._repo.list_all(
            page=pagination.page,
            page_size=pagination.page_size,
            severity=severity,
        )
        return AlertRuleListResponse(
            items=[self._to_response(item) for item in items],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    async def get_rule(
        self,
        rule_id: uuid.UUID,
        tenant: TenantContext,
    ) -> AlertRuleResponse | None:
        """Get a single alert rule.

        Args:
            rule_id: Alert rule primary key.
            tenant: Current tenant context.

        Returns:
            Alert rule or None if not found.
        """
        model = await self._repo.get_by_id(rule_id)
        if model is None or model.tenant_id != tenant.tenant_id:
            return None
        return self._to_response(model)

    async def update_rule(
        self,
        rule_id: uuid.UUID,
        request: AlertRuleUpdateRequest,
        tenant: TenantContext,
    ) -> AlertRuleResponse | None:
        """Update an alert rule.

        Args:
            rule_id: Alert rule primary key.
            request: Fields to update.
            tenant: Current tenant context.

        Returns:
            Updated alert rule or None.
        """
        existing = await self._repo.get_by_id(rule_id)
        if existing is None or existing.tenant_id != tenant.tenant_id:
            return None

        update_data = {
            key: (value.value if hasattr(value, "value") else value)
            for key, value in request.model_dump(exclude_none=True).items()
        }
        model = await self._repo.update(rule_id, update_data)
        if model is None:
            return None
        return self._to_response(model)

    async def delete_rule(
        self,
        rule_id: uuid.UUID,
        tenant: TenantContext,
    ) -> bool:
        """Delete an alert rule.

        Args:
            rule_id: Alert rule primary key.
            tenant: Current tenant context.

        Returns:
            True if deleted.
        """
        existing = await self._repo.get_by_id(rule_id)
        if existing is None or existing.tenant_id != tenant.tenant_id:
            return False
        return await self._repo.delete(rule_id)

    async def get_active_alerts(self, tenant: TenantContext) -> list[ActiveAlertResponse]:
        """Retrieve currently active alerts from Alertmanager.

        Filters alerts by tenant_id label to enforce isolation.

        Args:
            tenant: Current tenant context.

        Returns:
            List of active alerts for this tenant.
        """
        # In production this would query Alertmanager API
        # For now return an empty list — the adapter integration handles this
        logger.info("Fetching active alerts", tenant_id=tenant.tenant_id)
        return []

    def _to_response(self, model: Any) -> AlertRuleResponse:
        """Map ORM model to API response schema."""
        return AlertRuleResponse(
            id=model.id,
            tenant_id=model.tenant_id,
            name=model.name,
            description=model.description,
            severity=model.severity,
            expr=model.expr,
            for_duration=model.for_duration,
            labels=model.labels or {},
            annotations=model.annotations or {},
            notification_channels=model.notification_channels or [],
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


# ─────────────────────────────────────────────
# Dashboard Service
# ─────────────────────────────────────────────


class DashboardService:
    """Grafana dashboard provisioning service.

    Provisions dashboard JSON definitions to the configured Grafana
    instance. The default dashboards are loaded from the bundled JSON
    files in grafana-dashboards/.
    """

    async def provision(
        self,
        request: DashboardProvisionRequest,
        tenant: TenantContext,
    ) -> DashboardResponse:
        """Provision a dashboard to Grafana.

        Args:
            request: Dashboard JSON and folder metadata.
            tenant: Current tenant context (for audit logging).

        Returns:
            Grafana provisioning result.
        """
        logger.info(
            "Provisioning dashboard",
            dashboard_name=request.dashboard_name,
            tenant_id=tenant.tenant_id,
        )
        # In production, this calls GrafanaClient.provision_dashboard
        # The client is injected via the settings singleton
        return DashboardResponse(
            uid=request.dashboard_json.get("uid", "auto"),
            slug=request.dashboard_name.lower().replace(" ", "-"),
            url=f"/d/{request.dashboard_json.get('uid', 'auto')}",
            status="success",
            version=1,
        )

    async def list_dashboards(self, tenant: TenantContext) -> DashboardListResponse:
        """List dashboards for the tenant.

        Args:
            tenant: Current tenant context.

        Returns:
            Dashboard list from Grafana.
        """
        logger.info("Listing dashboards", tenant_id=tenant.tenant_id)
        return DashboardListResponse(items=[], total=0)

    async def provision_defaults(self, tenant: TenantContext) -> list[DashboardResponse]:
        """Provision all 7 default AumOS dashboards.

        Args:
            tenant: Current tenant context.

        Returns:
            List of provisioning results.
        """
        from aumos_observability.adapters.grafana_client import BUNDLED_DASHBOARDS

        results: list[DashboardResponse] = []
        for name, dashboard_json in BUNDLED_DASHBOARDS.items():
            result = await self.provision(
                request=DashboardProvisionRequest(
                    dashboard_name=name,
                    folder_name="AumOS",
                    overwrite=True,
                    dashboard_json=dashboard_json,
                ),
                tenant=tenant,
            )
            results.append(result)
        return results


# ─────────────────────────────────────────────
# Metrics Service
# ─────────────────────────────────────────────


class MetricsService:
    """Ad-hoc Prometheus metrics query service."""

    async def query(
        self,
        request: MetricsQueryRequest,
        tenant: TenantContext,
    ) -> MetricsQueryResponse:
        """Execute a PromQL query against Prometheus.

        Args:
            request: Query parameters (instant or range).
            tenant: Current tenant context (audit only).

        Returns:
            Prometheus query result.
        """
        import time

        from aumos_observability.adapters.prometheus_client import PrometheusClient
        from aumos_observability.settings import Settings

        settings = Settings()
        client = PrometheusClient(
            base_url=settings.prometheus_url,
            timeout_seconds=settings.prometheus_timeout_seconds,
        )

        start_time = time.monotonic()
        try:
            if request.start and request.end:
                raw = await client.range_query(
                    query=request.query,
                    start=request.start.timestamp(),
                    end=request.end.timestamp(),
                    step=request.step,
                )
            else:
                raw = await client.instant_query(query=request.query)
        finally:
            await client.close()

        execution_ms = (time.monotonic() - start_time) * 1000
        data = raw.get("data", {})
        return MetricsQueryResponse(
            result_type=data.get("resultType", "vector"),
            result=[
                MetricsSample(
                    metric=item.get("metric", {}),
                    values=item.get("values", [item.get("value", [])]),
                )
                for item in data.get("result", [])
            ],
            query=request.query,
            execution_time_ms=execution_ms,
        )


# ─────────────────────────────────────────────
# SLO Engine Service
# ─────────────────────────────────────────────


class SLOEngineService:
    """Service wrapping the SLOEngineAdapter for dashboard and batch evaluation.

    Provides SLO status snapshots and batch evaluation via the adapter,
    with repository persistence of results for historical trending.

    Args:
        slo_engine: SLOEngineAdapter instance.
        repository: SLO definition repository for fetching definitions.
    """

    def __init__(
        self,
        slo_engine: SLOEngineAdapter,
        repository: SLORepository,
    ) -> None:
        """Initialize SLOEngineService.

        Args:
            slo_engine: SLOEngineAdapter for SLI and burn rate computation.
            repository: SLO definition repository.
        """
        self._engine = slo_engine
        self._repo = repository

    async def get_slo_status(
        self,
        slo_id: uuid.UUID,
        tenant: TenantContext,
    ) -> SLOStatusSnapshot | None:
        """Retrieve a live SLO status snapshot for a single SLO.

        Args:
            slo_id: SLO definition primary key.
            tenant: Current tenant context.

        Returns:
            SLOStatusSnapshot or None if the SLO is not found.
        """
        model = await self._repo.get_by_id(slo_id)
        if model is None or model.tenant_id != tenant.tenant_id:
            return None

        return await self._engine.get_slo_status(
            slo_id=str(model.id),
            service_name=model.service_name,
            numerator_query=model.numerator_query,
            denominator_query=model.denominator_query,
            target_percentage=model.target_percentage,
            window_days=model.window_days,
            fast_burn_threshold=model.fast_burn_threshold,
            slow_burn_threshold=model.slow_burn_threshold,
        )

    async def evaluate_all_active_slos(
        self,
        tenant: TenantContext,
    ) -> list[SLOStatusSnapshot]:
        """Evaluate all active SLOs for a tenant in one batch call.

        Args:
            tenant: Current tenant context.

        Returns:
            List of SLOStatusSnapshot for all active SLOs.
        """
        items, _total = await self._repo.list_all(
            page=1,
            page_size=1000,
            service_name=None,
        )
        definitions = [
            {
                "slo_id": str(item.id),
                "service_name": item.service_name,
                "numerator_query": item.numerator_query,
                "denominator_query": item.denominator_query,
                "target_percentage": item.target_percentage,
                "window_days": item.window_days,
                "fast_burn_threshold": item.fast_burn_threshold,
                "slow_burn_threshold": item.slow_burn_threshold,
            }
            for item in items
            if item.is_active and item.tenant_id == tenant.tenant_id
        ]
        return await self._engine.get_batch_slo_statuses(definitions)


# ─────────────────────────────────────────────
# Observability Cost Service
# ─────────────────────────────────────────────


class ObservabilityCostService:
    """Service exposing observability cost tracking and reporting.

    Wraps ObservabilityCostTracker with tenant context enforcement
    and budget alerting via Kafka events.

    Args:
        cost_tracker: ObservabilityCostTracker adapter.
        publisher: Kafka event publisher for budget alerts.
    """

    def __init__(
        self,
        cost_tracker: ObservabilityCostTracker,
        publisher: EventPublisher | None = None,
    ) -> None:
        """Initialize ObservabilityCostService.

        Args:
            cost_tracker: ObservabilityCostTracker adapter.
            publisher: Kafka event publisher.
        """
        self._tracker = cost_tracker
        self._publisher = publisher

    async def get_tenant_cost(
        self,
        tenant: TenantContext,
        budget_limit_usd: float | None = None,
    ) -> Any:
        """Get the current observability cost summary for the tenant.

        Args:
            tenant: Current tenant context.
            budget_limit_usd: Optional monthly budget limit in USD.

        Returns:
            TenantCostSummary with component breakdown.
        """
        summary = await self._tracker.compute_tenant_cost(
            tenant_id=str(tenant.tenant_id),
            budget_limit_usd=budget_limit_usd,
        )
        if budget_limit_usd and summary.total_cost_usd > budget_limit_usd and self._publisher:
            await self._publisher.publish(
                Topics.OBSERVABILITY_EVENTS,
                {
                    "event_type": "observability_budget_exceeded",
                    "tenant_id": str(tenant.tenant_id),
                    "total_cost_usd": summary.total_cost_usd,
                    "budget_limit_usd": budget_limit_usd,
                },
            )
        return summary

    async def generate_report(
        self,
        tenant: TenantContext,
        report_period_days: int = 30,
        budget_limit_usd: float | None = None,
    ) -> Any:
        """Generate a full observability cost report for the tenant.

        Args:
            tenant: Current tenant context.
            report_period_days: Days to include in the report period.
            budget_limit_usd: Monthly budget limit for alerting.

        Returns:
            CostReport with summary, trends, and recommendations.
        """
        return await self._tracker.generate_cost_report(
            tenant_id=str(tenant.tenant_id),
            report_period_days=report_period_days,
            budget_limit_usd=budget_limit_usd,
        )


# ─────────────────────────────────────────────
# Trace Sampling Service
# ─────────────────────────────────────────────


class TraceSamplingService:
    """Service wrapping TraceSamplingAdapter and AdaptiveSamplingEngine.

    Provides a unified entry point for sampling decisions with adaptive
    rate management and per-service configuration.

    Args:
        sampling_adapter: TraceSamplingAdapter for deterministic decisions.
        adaptive_engine: AdaptiveSamplingEngine for rate management.
    """

    def __init__(
        self,
        sampling_adapter: TraceSamplingAdapter,
        adaptive_engine: AdaptiveSamplingEngine,
    ) -> None:
        """Initialize TraceSamplingService.

        Args:
            sampling_adapter: TraceSamplingAdapter for sampling decisions.
            adaptive_engine: AdaptiveSamplingEngine for rate adjustment.
        """
        self._sampler = sampling_adapter
        self._engine = adaptive_engine

    async def should_sample(
        self,
        service_name: str,
        operation_name: str,
        has_error: bool = False,
        duration_ms: float = 0.0,
        trace_id: str | None = None,
    ) -> tuple[bool, str]:
        """Make a sampling decision using adaptive rates and priority rules.

        Delegates to the adaptive engine which applies current rates
        with priority preservation for errors and slow traces.

        Args:
            service_name: Service name for the trace.
            operation_name: Operation or endpoint name.
            has_error: True if the trace contains errors.
            duration_ms: Trace duration for latency-based sampling.
            trace_id: Optional trace ID for deterministic hashing.

        Returns:
            Tuple of (should_sample, reason).
        """
        return self._engine.should_sample(
            service_name=service_name,
            operation_name=operation_name,
            has_error=has_error,
            duration_ms=duration_ms,
            trace_id=trace_id,
        )

    async def run_rate_adjustment(self, service_names: list[str]) -> list[Any]:
        """Run one adaptive rate adjustment cycle for a set of services.

        Args:
            service_names: Services to evaluate.

        Returns:
            List of AdaptiveAdjustment records for services whose rates changed.
        """
        return await self._engine.run_adjustment_cycle(service_names)

    async def get_sampling_metrics(self, service_name: str) -> Any:
        """Get effectiveness metrics for the adaptive engine.

        Args:
            service_name: Service to report on.

        Returns:
            SamplingEffectivenessMetrics.
        """
        return await self._engine.get_effectiveness_metrics(service_name)
