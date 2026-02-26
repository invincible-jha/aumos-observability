"""SLO management CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from aumos_common.auth import TenantContext, get_current_tenant
from aumos_common.database import get_db_session
from aumos_common.errors import NotFoundError
from aumos_common.observability import get_logger
from aumos_common.pagination import PageRequest

from aumos_observability.adapters.repositories import SLORepository
from aumos_observability.api.schemas import (
    SLOBurnRateResponse,
    SLOCreateRequest,
    SLOListResponse,
    SLOResponse,
    SLOUpdateRequest,
)
from aumos_observability.core.services import SLOService

logger = get_logger(__name__)
router = APIRouter(prefix="/slos", tags=["SLO Management"])


def _get_slo_service(
    session: AsyncSession = Depends(get_db_session),
) -> SLOService:
    """Dependency — creates a SLOService with the current DB session."""
    repo = SLORepository(session)
    return SLOService(repository=repo)


@router.post("", response_model=SLOResponse, status_code=201)
async def create_slo(
    request: SLOCreateRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    service: SLOService = Depends(_get_slo_service),
) -> SLOResponse:
    """Create a new SLO definition.

    Args:
        request: SLO creation payload.
        tenant: Current tenant context from JWT.
        service: SLO business logic service.

    Returns:
        The newly created SLO with burn rate status.
    """
    logger.info("Creating SLO", slo_name=request.name, tenant_id=tenant.tenant_id)
    return await service.create_slo(request=request, tenant=tenant)


@router.get("", response_model=SLOListResponse)
async def list_slos(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service_name: str | None = Query(default=None),
    tenant: TenantContext = Depends(get_current_tenant),
    service: SLOService = Depends(_get_slo_service),
) -> SLOListResponse:
    """List all SLO definitions for the current tenant.

    Args:
        page: Page number (1-based).
        page_size: Number of results per page.
        service_name: Optional filter by service name.
        tenant: Current tenant context.
        service: SLO service.

    Returns:
        Paginated list of SLO definitions.
    """
    pagination = PageRequest(page=page, page_size=page_size)
    return await service.list_slos(
        tenant=tenant,
        pagination=pagination,
        service_name=service_name,
    )


@router.get("/{slo_id}", response_model=SLOResponse)
async def get_slo(
    slo_id: uuid.UUID = Path(description="SLO UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    service: SLOService = Depends(_get_slo_service),
) -> SLOResponse:
    """Get a single SLO definition by ID.

    Args:
        slo_id: SLO primary key.
        tenant: Current tenant context.
        service: SLO service.

    Returns:
        SLO definition with current burn rate status.

    Raises:
        NotFoundError: If the SLO does not exist or belongs to another tenant.
    """
    result = await service.get_slo(slo_id=slo_id, tenant=tenant)
    if result is None:
        raise NotFoundError(resource="SLO", resource_id=str(slo_id))
    return result


@router.put("/{slo_id}", response_model=SLOResponse)
async def update_slo(
    request: SLOUpdateRequest,
    slo_id: uuid.UUID = Path(description="SLO UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    service: SLOService = Depends(_get_slo_service),
) -> SLOResponse:
    """Update an existing SLO definition.

    Args:
        request: Fields to update (partial update).
        slo_id: SLO primary key.
        tenant: Current tenant context.
        service: SLO service.

    Returns:
        Updated SLO definition.

    Raises:
        NotFoundError: If the SLO does not exist.
    """
    result = await service.update_slo(slo_id=slo_id, request=request, tenant=tenant)
    if result is None:
        raise NotFoundError(resource="SLO", resource_id=str(slo_id))
    return result


@router.delete("/{slo_id}", status_code=204)
async def delete_slo(
    slo_id: uuid.UUID = Path(description="SLO UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    service: SLOService = Depends(_get_slo_service),
) -> None:
    """Delete an SLO definition.

    Args:
        slo_id: SLO primary key.
        tenant: Current tenant context.
        service: SLO service.

    Raises:
        NotFoundError: If the SLO does not exist.
    """
    deleted = await service.delete_slo(slo_id=slo_id, tenant=tenant)
    if not deleted:
        raise NotFoundError(resource="SLO", resource_id=str(slo_id))


@router.get("/{slo_id}/burn-rate", response_model=SLOBurnRateResponse)
async def get_slo_burn_rate(
    slo_id: uuid.UUID = Path(description="SLO UUID"),
    tenant: TenantContext = Depends(get_current_tenant),
    service: SLOService = Depends(_get_slo_service),
) -> SLOBurnRateResponse:
    """Get the current burn rate calculation for an SLO.

    Args:
        slo_id: SLO primary key.
        tenant: Current tenant context.
        service: SLO service.

    Returns:
        Current burn rate metrics for the SLO.

    Raises:
        NotFoundError: If the SLO does not exist.
    """
    result = await service.calculate_burn_rate(slo_id=slo_id, tenant=tenant)
    if result is None:
        raise NotFoundError(resource="SLO", resource_id=str(slo_id))
    return result
