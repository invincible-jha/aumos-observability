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
