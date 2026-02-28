"""Main API router — aggregates all sub-routers."""

from fastapi import APIRouter, Depends

from aumos_common.auth import TenantContext, get_current_tenant
from aumos_common.observability import get_logger

from aumos_observability.api.alert_routes import router as alert_router
from aumos_observability.api.dashboard_routes import router as dashboard_router
from aumos_observability.api.routes.alerting import router as correlation_router
from aumos_observability.api.routes.anomaly_routes import router as anomaly_router
from aumos_observability.api.schemas import MetricsQueryRequest, MetricsQueryResponse
from aumos_observability.api.slo_routes import router as slo_router
from aumos_observability.core.services import MetricsService

logger = get_logger(__name__)

router = APIRouter()

# Mount sub-routers
router.include_router(slo_router)
router.include_router(alert_router)
router.include_router(dashboard_router)
router.include_router(correlation_router)
router.include_router(anomaly_router)


# ─────────────────────────────────────────────
# Ad-hoc metrics query (admin/power-user feature)
# ─────────────────────────────────────────────


@router.post("/metrics/query", response_model=MetricsQueryResponse, tags=["Metrics"])
async def query_metrics(
    request: MetricsQueryRequest,
    tenant: TenantContext = Depends(get_current_tenant),
) -> MetricsQueryResponse:
    """Execute an ad-hoc PromQL query against Prometheus.

    Supports both instant queries and range queries. For range queries,
    provide both `start` and `end` timestamps along with a `step` interval.

    Args:
        request: PromQL query parameters.
        tenant: Current tenant context (used for audit logging).

    Returns:
        Prometheus query result with samples.
    """
    service = MetricsService()
    logger.info(
        "Executing metrics query",
        tenant_id=tenant.tenant_id,
        query=request.query[:100],
    )
    return await service.query(request=request, tenant=tenant)
