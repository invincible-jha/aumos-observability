"""Alert rule management endpoints."""

import uuid

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from aumos_common.auth import TenantContext, get_current_tenant
from aumos_common.database import get_db_session
from aumos_common.errors import NotFoundError
from aumos_common.observability import get_logger
from aumos_common.pagination import PageRequest

from aumos_observability.adapters.repositories import AlertRuleRepository
from aumos_observability.api.schemas import (
    ActiveAlertResponse,
    AlertRuleCreateRequest,
    AlertRuleListResponse,
    AlertRuleResponse,
    AlertRuleUpdateRequest,
)
from aumos_observability.core.services import AlertService

logger = get_logger(__name__)
router = APIRouter(prefix="/alerts", tags=["Alert Management"])


def _get_alert_service(
    session: AsyncSession = Depends(get_db_session),
) -> AlertService:
    """Dependency — creates an AlertService with the current DB session."""
    repo = AlertRuleRepository(session)
    return AlertService(repository=repo)


@router.post("/rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    request: AlertRuleCreateRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    service: AlertService = Depends(_get_alert_service),
) -> AlertRuleResponse:
    """Create a new alert rule.

    Args:
        request: Alert rule creation payload.
        tenant: Current tenant context.
        service: Alert management service.

    Returns:
        The newly created alert rule.
    """
    logger.info("Creating alert rule", rule_name=request.name, tenant_id=tenant.tenant_id)
    return await service.create_rule(request=request, tenant=tenant)


@router.get("/rules", response_model=AlertRuleListResponse)
async def list_alert_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    severity: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    service: AlertService = Depends(_get_alert_service),
) -> AlertRuleListResponse:
    """List all alert rules for the current tenant.

    Args:
        page: Page number (1-based).
        page_size: Results per page.
        severity: Optional filter by severity level.
        tenant: Current tenant context.
        service: Alert service.

    Returns:
        Paginated list of alert rules.
    """
    pagination = PageRequest(page=page, page_size=page_size)
    return await service.list_rules(
        tenant=tenant,
        pagination=pagination,
        severity=severity,
    )


@router.get("/rules/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    rule_id: uuid.UUID = Path(description="Alert rule UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    service: AlertService = Depends(_get_alert_service),
) -> AlertRuleResponse:
    """Get a single alert rule by ID.

    Args:
        rule_id: Alert rule primary key.
        tenant: Current tenant context.
        service: Alert service.

    Returns:
        Alert rule definition.

    Raises:
        NotFoundError: If rule does not exist or belongs to another tenant.
    """
    result = await service.get_rule(rule_id=rule_id, tenant=tenant)
    if result is None:
        raise NotFoundError(resource="AlertRule", resource_id=str(rule_id))
    return result


@router.put("/rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    request: AlertRuleUpdateRequest,
    rule_id: uuid.UUID = Path(description="Alert rule UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    service: AlertService = Depends(_get_alert_service),
) -> AlertRuleResponse:
    """Update an existing alert rule.

    Args:
        request: Fields to update.
        rule_id: Alert rule primary key.
        tenant: Current tenant context.
        service: Alert service.

    Returns:
        Updated alert rule.

    Raises:
        NotFoundError: If rule does not exist.
    """
    result = await service.update_rule(rule_id=rule_id, request=request, tenant=tenant)
    if result is None:
        raise NotFoundError(resource="AlertRule", resource_id=str(rule_id))
    return result


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: uuid.UUID = Path(description="Alert rule UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    service: AlertService = Depends(_get_alert_service),
) -> None:
    """Delete an alert rule.

    Args:
        rule_id: Alert rule primary key.
        tenant: Current tenant context.
        service: Alert service.

    Raises:
        NotFoundError: If rule does not exist.
    """
    deleted = await service.delete_rule(rule_id=rule_id, tenant=tenant)
    if not deleted:
        raise NotFoundError(resource="AlertRule", resource_id=str(rule_id))


@router.get("/active", response_model=list[ActiveAlertResponse])
async def list_active_alerts(
    tenant: TenantContext = Depends(get_current_tenant),
    service: AlertService = Depends(_get_alert_service),
) -> list[ActiveAlertResponse]:
    """List currently firing alerts from Alertmanager.

    Args:
        tenant: Current tenant context.
        service: Alert service.

    Returns:
        List of currently active/firing alerts.
    """
    return await service.get_active_alerts(tenant=tenant)
