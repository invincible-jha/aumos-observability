"""Dashboard provisioning endpoints."""

from fastapi import APIRouter, Depends

from aumos_common.auth import TenantContext, get_current_tenant
from aumos_common.observability import get_logger

from aumos_observability.api.schemas import (
    DashboardListResponse,
    DashboardProvisionRequest,
    DashboardResponse,
)
from aumos_observability.core.services import DashboardService

logger = get_logger(__name__)
router = APIRouter(prefix="/dashboards", tags=["Dashboard Management"])


def _get_dashboard_service() -> DashboardService:
    """Dependency — creates a DashboardService instance."""
    return DashboardService()


@router.post("/provision", response_model=DashboardResponse, status_code=201)
async def provision_dashboard(
    request: DashboardProvisionRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    service: DashboardService = Depends(_get_dashboard_service),
) -> DashboardResponse:
    """Provision a dashboard to Grafana.

    Uploads the provided JSON dashboard definition to the configured
    Grafana instance, placing it in the specified folder.

    Args:
        request: Dashboard JSON and metadata.
        tenant: Current tenant context.
        service: Dashboard provisioning service.

    Returns:
        Grafana provisioning result with dashboard URL.
    """
    logger.info(
        "Provisioning dashboard",
        dashboard_name=request.dashboard_name,
        tenant_id=tenant.tenant_id,
    )
    return await service.provision(request=request, tenant=tenant)


@router.get("", response_model=DashboardListResponse)
async def list_dashboards(
    tenant: TenantContext = Depends(get_current_tenant),
    service: DashboardService = Depends(_get_dashboard_service),
) -> DashboardListResponse:
    """List all dashboards provisioned for the current tenant.

    Args:
        tenant: Current tenant context.
        service: Dashboard service.

    Returns:
        List of provisioned dashboards.
    """
    return await service.list_dashboards(tenant=tenant)


@router.post("/provision-defaults", response_model=list[DashboardResponse], status_code=201)
async def provision_default_dashboards(
    tenant: TenantContext = Depends(get_current_tenant),
    service: DashboardService = Depends(_get_dashboard_service),
) -> list[DashboardResponse]:
    """Provision all default AumOS dashboards to Grafana.

    Provisions all 7 standard AumOS dashboards:
    - Infrastructure Overview
    - LLM Operations
    - Agent Workflow
    - Governance & Compliance
    - Board / Executive
    - Cost Attribution
    - Security Posture

    Args:
        tenant: Current tenant context.
        service: Dashboard service.

    Returns:
        List of provisioning results for all dashboards.
    """
    logger.info("Provisioning default dashboards", tenant_id=tenant.tenant_id)
    return await service.provision_defaults(tenant=tenant)
