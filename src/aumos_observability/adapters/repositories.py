"""SQLAlchemy repositories for the Observability Stack.

Implements persistence for:
- AlertRuleRepository — obs_alert_rules
- AlertHistoryRepository — obs_alert_history
- DashboardRepository — obs_dashboards
- SLODefinitionRepository — obs_slo_definitions
- SLOBudgetRepository — obs_slo_budgets
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aumos_common.observability import get_logger

from aumos_observability.core.models import AlertRule, SLODefinition

logger = get_logger(__name__)


class AlertRuleRepository:
    """Repository for alert rule persistence.

    Provides CRUD operations against the obs_alert_rules table.
    Tenant isolation is enforced via RLS set by aumos-common session middleware.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def create(self, data: dict[str, Any]) -> AlertRule:
        """Persist a new alert rule.

        Args:
            data: Dictionary of field values to set on the new record.

        Returns:
            The newly created AlertRule ORM instance.
        """
        model = AlertRule(**data)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        logger.debug("AlertRule created", rule_id=str(model.id))
        return model

    async def get_by_id(self, rule_id: uuid.UUID) -> AlertRule | None:
        """Retrieve an alert rule by primary key.

        Args:
            rule_id: UUID primary key.

        Returns:
            AlertRule instance or None if not found.
        """
        result = await self._session.execute(
            select(AlertRule).where(AlertRule.id == rule_id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        page: int,
        page_size: int,
        severity: str | None = None,
    ) -> tuple[list[AlertRule], int]:
        """Return paginated alert rules with optional severity filter.

        Args:
            page: 1-based page number.
            page_size: Number of results per page.
            severity: Optional severity level filter.

        Returns:
            Tuple of (items, total_count).
        """
        query = select(AlertRule)
        count_query = select(func.count()).select_from(AlertRule)

        if severity is not None:
            query = query.where(AlertRule.severity == severity)
            count_query = count_query.where(AlertRule.severity == severity)

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(AlertRule.created_at.desc())

        results = await self._session.execute(query)
        count_result = await self._session.execute(count_query)

        return list(results.scalars().all()), count_result.scalar_one()

    async def update(self, rule_id: uuid.UUID, data: dict[str, Any]) -> AlertRule | None:
        """Update an existing alert rule.

        Args:
            rule_id: UUID primary key.
            data: Dictionary of fields to update.

        Returns:
            Updated AlertRule or None if not found.
        """
        model = await self.get_by_id(rule_id)
        if model is None:
            return None

        for field, value in data.items():
            setattr(model, field, value)

        await self._session.commit()
        await self._session.refresh(model)
        logger.debug("AlertRule updated", rule_id=str(rule_id))
        return model

    async def delete(self, rule_id: uuid.UUID) -> bool:
        """Delete an alert rule.

        Args:
            rule_id: UUID primary key.

        Returns:
            True if deleted, False if not found.
        """
        model = await self.get_by_id(rule_id)
        if model is None:
            return False

        await self._session.delete(model)
        await self._session.commit()
        logger.debug("AlertRule deleted", rule_id=str(rule_id))
        return True


class AlertHistoryRepository:
    """Repository for alert history persistence.

    Stores fired alert events against the obs_alert_history table.
    Used for audit trails and incident post-mortems.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def create(self, data: dict[str, Any]) -> Any:
        """Persist a new alert history record.

        Args:
            data: Alert event data including rule_id, state, labels, fired_at.

        Returns:
            The newly created history record ORM instance.
        """
        from aumos_observability.core.models import AlertHistory

        model = AlertHistory(**data)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        logger.debug("AlertHistory created", record_id=str(model.id))
        return model

    async def list_by_rule(
        self,
        rule_id: uuid.UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[Any], int]:
        """List alert history entries for a specific rule.

        Args:
            rule_id: UUID of the parent alert rule.
            page: 1-based page number.
            page_size: Results per page.

        Returns:
            Tuple of (items, total_count).
        """
        from aumos_observability.core.models import AlertHistory

        query = select(AlertHistory).where(AlertHistory.alert_rule_id == rule_id)
        count_query = (
            select(func.count())
            .select_from(AlertHistory)
            .where(AlertHistory.alert_rule_id == rule_id)
        )

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(AlertHistory.fired_at.desc())

        results = await self._session.execute(query)
        count_result = await self._session.execute(count_query)

        return list(results.scalars().all()), count_result.scalar_one()


class DashboardRepository:
    """Repository for dashboard metadata persistence.

    Stores dashboard provisioning records against obs_dashboards.
    The full dashboard JSON is stored in Grafana; this table tracks
    which dashboards have been provisioned per tenant.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def create(self, data: dict[str, Any]) -> Any:
        """Persist a dashboard provisioning record.

        Args:
            data: Dashboard metadata including uid, name, folder, grafana_url.

        Returns:
            The newly created Dashboard ORM instance.
        """
        from aumos_observability.core.models import Dashboard

        model = Dashboard(**data)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        logger.debug("Dashboard record created", uid=data.get("uid"))
        return model

    async def get_by_uid(self, uid: str) -> Any | None:
        """Retrieve a dashboard by Grafana UID.

        Args:
            uid: Grafana dashboard UID.

        Returns:
            Dashboard instance or None if not found.
        """
        from aumos_observability.core.models import Dashboard

        result = await self._session.execute(
            select(Dashboard).where(Dashboard.uid == uid)
        )
        return result.scalar_one_or_none()

    async def list_all(self, page: int, page_size: int) -> tuple[list[Any], int]:
        """List all dashboard records for the current tenant.

        Args:
            page: 1-based page number.
            page_size: Results per page.

        Returns:
            Tuple of (items, total_count).
        """
        from aumos_observability.core.models import Dashboard

        query = select(Dashboard)
        count_query = select(func.count()).select_from(Dashboard)

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(Dashboard.created_at.desc())

        results = await self._session.execute(query)
        count_result = await self._session.execute(count_query)

        return list(results.scalars().all()), count_result.scalar_one()

    async def delete(self, dashboard_id: uuid.UUID) -> bool:
        """Delete a dashboard record.

        Args:
            dashboard_id: UUID primary key.

        Returns:
            True if deleted.
        """
        from aumos_observability.core.models import Dashboard

        result = await self._session.execute(
            select(Dashboard).where(Dashboard.id == dashboard_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return False

        await self._session.delete(model)
        await self._session.commit()
        return True


class SLODefinitionRepository:
    """Repository for SLO definition persistence.

    Provides CRUD against obs_slo_definitions. Also used by the SLO engine
    background task to fetch all active SLOs for periodic evaluation.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def create(self, data: dict[str, Any]) -> SLODefinition:
        """Persist a new SLO definition.

        Args:
            data: Dictionary of field values for the new SLO.

        Returns:
            The newly created SLODefinition ORM instance.
        """
        model = SLODefinition(**data)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        logger.debug("SLODefinition created", slo_id=str(model.id))
        return model

    async def get_by_id(self, slo_id: uuid.UUID) -> SLODefinition | None:
        """Retrieve an SLO definition by primary key.

        Args:
            slo_id: UUID primary key.

        Returns:
            SLODefinition instance or None if not found.
        """
        result = await self._session.execute(
            select(SLODefinition).where(SLODefinition.id == slo_id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        page: int,
        page_size: int,
        service_name: str | None = None,
    ) -> tuple[list[SLODefinition], int]:
        """Return paginated SLO definitions with optional service filter.

        Args:
            page: 1-based page number.
            page_size: Results per page.
            service_name: Optional filter by service name.

        Returns:
            Tuple of (items, total_count).
        """
        query = select(SLODefinition)
        count_query = select(func.count()).select_from(SLODefinition)

        if service_name is not None:
            query = query.where(SLODefinition.service_name == service_name)
            count_query = count_query.where(SLODefinition.service_name == service_name)

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(SLODefinition.created_at.desc())

        results = await self._session.execute(query)
        count_result = await self._session.execute(count_query)

        return list(results.scalars().all()), count_result.scalar_one()

    async def list_active(self) -> list[SLODefinition]:
        """Return all active SLO definitions across all tenants.

        Used by the SLO engine background task for periodic evaluation.
        Note: This bypasses tenant RLS — only call from trusted background tasks.

        Returns:
            All SLO definitions with is_active=True.
        """
        result = await self._session.execute(
            select(SLODefinition).where(SLODefinition.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def update(self, slo_id: uuid.UUID, data: dict[str, Any]) -> SLODefinition | None:
        """Update an existing SLO definition.

        Args:
            slo_id: UUID primary key.
            data: Fields to update.

        Returns:
            Updated SLODefinition or None if not found.
        """
        model = await self.get_by_id(slo_id)
        if model is None:
            return None

        for field, value in data.items():
            setattr(model, field, value)

        await self._session.commit()
        await self._session.refresh(model)
        logger.debug("SLODefinition updated", slo_id=str(slo_id))
        return model

    async def delete(self, slo_id: uuid.UUID) -> bool:
        """Delete an SLO definition.

        Args:
            slo_id: UUID primary key.

        Returns:
            True if deleted, False if not found.
        """
        model = await self.get_by_id(slo_id)
        if model is None:
            return False

        await self._session.delete(model)
        await self._session.commit()
        logger.debug("SLODefinition deleted", slo_id=str(slo_id))
        return True


# Alias used by slo_routes.py (imports SLORepository)
SLORepository = SLODefinitionRepository


class SLOBudgetRepository:
    """Repository for SLO error budget snapshots.

    Stores point-in-time error budget calculations against obs_slo_budgets.
    Used for historical trending and burn rate dashboards.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an async SQLAlchemy session.

        Args:
            session: Active async database session.
        """
        self._session = session

    async def create(self, data: dict[str, Any]) -> Any:
        """Persist an error budget snapshot.

        Args:
            data: Budget snapshot data including slo_id, fast/slow burn rates,
                  error_budget_minutes, snapshot_at.

        Returns:
            The newly created SLOBudget ORM instance.
        """
        from aumos_observability.core.models import SLOBudget

        model = SLOBudget(**data)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        logger.debug("SLOBudget snapshot created", slo_id=data.get("slo_id"))
        return model

    async def list_by_slo(
        self,
        slo_id: uuid.UUID,
        limit: int = 100,
    ) -> list[Any]:
        """List budget snapshots for an SLO, most recent first.

        Args:
            slo_id: SLO UUID to fetch snapshots for.
            limit: Maximum number of snapshots to return.

        Returns:
            List of SLOBudget snapshots.
        """
        from aumos_observability.core.models import SLOBudget

        result = await self._session.execute(
            select(SLOBudget)
            .where(SLOBudget.slo_id == slo_id)
            .order_by(SLOBudget.snapshot_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
