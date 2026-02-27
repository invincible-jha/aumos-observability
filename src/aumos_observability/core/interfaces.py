"""Abstract interfaces (Protocol classes) for the Observability core layer."""

import uuid
from typing import Any, Protocol, runtime_checkable

from aumos_observability.api.schemas import (
    AlertRuleCreateRequest,
    AlertRuleResponse,
    AlertRuleUpdateRequest,
    SLOCreateRequest,
    SLOResponse,
    SLOUpdateRequest,
)


@runtime_checkable
class ISLORepository(Protocol):
    """Interface for SLO definition persistence."""

    async def create(self, data: dict[str, Any]) -> Any:
        """Persist a new SLO definition."""
        ...

    async def get_by_id(self, slo_id: uuid.UUID) -> Any | None:
        """Retrieve an SLO by primary key."""
        ...

    async def list_all(
        self,
        page: int,
        page_size: int,
        service_name: str | None,
    ) -> tuple[list[Any], int]:
        """Return paginated SLO list and total count."""
        ...

    async def update(self, slo_id: uuid.UUID, data: dict[str, Any]) -> Any | None:
        """Update an existing SLO; returns updated record or None if not found."""
        ...

    async def delete(self, slo_id: uuid.UUID) -> bool:
        """Delete an SLO; returns True if deleted."""
        ...


@runtime_checkable
class IAlertRuleRepository(Protocol):
    """Interface for alert rule persistence."""

    async def create(self, data: dict[str, Any]) -> Any:
        """Persist a new alert rule."""
        ...

    async def get_by_id(self, rule_id: uuid.UUID) -> Any | None:
        """Retrieve an alert rule by primary key."""
        ...

    async def list_all(
        self,
        page: int,
        page_size: int,
        severity: str | None,
    ) -> tuple[list[Any], int]:
        """Return paginated alert rule list and total count."""
        ...

    async def update(self, rule_id: uuid.UUID, data: dict[str, Any]) -> Any | None:
        """Update an existing alert rule."""
        ...

    async def delete(self, rule_id: uuid.UUID) -> bool:
        """Delete an alert rule."""
        ...


@runtime_checkable
class IPrometheusClient(Protocol):
    """Interface for Prometheus API interactions."""

    async def instant_query(self, query: str) -> dict[str, Any]:
        """Execute an instant PromQL query."""
        ...

    async def range_query(
        self,
        query: str,
        start: float,
        end: float,
        step: str,
    ) -> dict[str, Any]:
        """Execute a range PromQL query."""
        ...

    async def health_check(self) -> bool:
        """Return True if Prometheus is reachable."""
        ...

    async def close(self) -> None:
        """Close underlying HTTP connections."""
        ...


@runtime_checkable
class IGrafanaClient(Protocol):
    """Interface for Grafana API interactions."""

    async def provision_dashboard(
        self,
        dashboard_json: dict[str, Any],
        folder_name: str,
        overwrite: bool,
    ) -> dict[str, Any]:
        """Provision a dashboard to Grafana; returns Grafana response."""
        ...

    async def list_dashboards(self, folder_name: str | None) -> list[dict[str, Any]]:
        """List dashboards from Grafana."""
        ...

    async def health_check(self) -> bool:
        """Return True if Grafana is reachable."""
        ...

    async def close(self) -> None:
        """Close underlying HTTP connections."""
        ...


@runtime_checkable
class ISLOEngine(Protocol):
    """Interface for SLO evaluation and multi-window burn rate alerting."""

    async def compute_sli(
        self,
        slo_id: str,
        numerator_query: str,
        denominator_query: str,
        window: str,
        sli_type: Any,
    ) -> Any:
        """Compute a Service Level Indicator from Prometheus data."""
        ...

    async def evaluate_multi_window(
        self,
        slo_id: str,
        numerator_query: str,
        denominator_query: str,
        target_percentage: float,
        window_days: int,
        fast_burn_threshold: float | None,
        slow_burn_threshold: float | None,
    ) -> Any:
        """Evaluate SLO using multi-window multi-burn-rate alerting."""
        ...

    async def get_slo_status(
        self,
        slo_id: str,
        service_name: str,
        numerator_query: str,
        denominator_query: str,
        target_percentage: float,
        window_days: int,
        fast_burn_threshold: float | None,
        slow_burn_threshold: float | None,
    ) -> Any:
        """Compute a complete SLO status snapshot for dashboard display."""
        ...

    async def get_batch_slo_statuses(
        self,
        slo_definitions: list[dict[str, Any]],
    ) -> list[Any]:
        """Compute SLO status snapshots for multiple SLOs."""
        ...


@runtime_checkable
class IObservabilityCostTracker(Protocol):
    """Interface for per-tenant observability cost tracking."""

    async def compute_tenant_cost(
        self,
        tenant_id: str,
        budget_limit_usd: float | None,
    ) -> Any:
        """Compute the current observability cost summary for a tenant."""
        ...

    async def generate_cost_report(
        self,
        tenant_id: str,
        report_period_days: int,
        budget_limit_usd: float | None,
    ) -> Any:
        """Generate a full observability cost report for a tenant."""
        ...

    async def check_budget_enforcement(
        self,
        tenant_id: str,
        budget_limit_usd: float,
    ) -> bool:
        """Check whether a tenant has exceeded their observability budget."""
        ...


@runtime_checkable
class ITraceSamplingAdapter(Protocol):
    """Interface for intelligent trace sampling decisions."""

    def configure_service(self, config: Any) -> None:
        """Set per-service sampling configuration."""
        ...

    def decide(self, trace: Any) -> Any:
        """Make a sampling decision for a single trace."""
        ...

    def decide_batch(self, traces: list[Any]) -> list[Any]:
        """Make sampling decisions for a batch of traces."""
        ...

    def analyze_impact(
        self,
        results: list[Any],
        period_seconds: float,
        service_name: str,
    ) -> Any:
        """Analyze sampling effectiveness over a period."""
        ...

    def get_service_configs(self) -> dict[str, Any]:
        """Return all configured service sampling configurations."""
        ...


@runtime_checkable
class IAdaptiveSamplingEngine(Protocol):
    """Interface for dynamic sampling rate adjustment."""

    async def compute_adjusted_rate(self, service_name: str) -> float:
        """Compute the optimal sample rate for a service given current traffic."""
        ...

    async def adjust_rate(self, service_name: str) -> Any | None:
        """Evaluate and apply a rate adjustment for a service."""
        ...

    def should_sample(
        self,
        service_name: str,
        operation_name: str,
        has_error: bool,
        duration_ms: float,
        trace_id: str | None,
    ) -> tuple[bool, str]:
        """Make an immediate sampling decision using current rates."""
        ...

    async def run_adjustment_cycle(self, service_names: list[str]) -> list[Any]:
        """Run one adjustment cycle for multiple services."""
        ...

    async def get_effectiveness_metrics(self, service_name: str) -> Any:
        """Compute effectiveness metrics for the adaptive engine."""
        ...

    def get_current_rates(self) -> dict[str, float]:
        """Return the current sampling rates for all tracked services."""
        ...
