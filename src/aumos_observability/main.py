"""AumOS Observability Stack service entry point."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from aumos_common.app import create_app
from aumos_common.database import init_database
from aumos_common.health import HealthCheck
from aumos_common.observability import get_logger

from aumos_observability.adapters.grafana_client import GrafanaClient
from aumos_observability.adapters.prometheus_client import PrometheusClient
from aumos_observability.core.services import SLOService
from aumos_observability.settings import Settings

logger = get_logger(__name__)
settings = Settings()

# Global service instances shared across request lifecycle
_prometheus_client: PrometheusClient | None = None
_grafana_client: GrafanaClient | None = None
_slo_service: SLOService | None = None
_slo_eval_task: asyncio.Task[None] | None = None


async def check_prometheus() -> bool:
    """Health check for Prometheus connectivity."""
    if _prometheus_client is None:
        return False
    return await _prometheus_client.health_check()


async def check_grafana() -> bool:
    """Health check for Grafana connectivity."""
    if _grafana_client is None:
        return False
    return await _grafana_client.health_check()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown."""
    global _prometheus_client, _grafana_client, _slo_service, _slo_eval_task

    logger.info("Starting AumOS Observability service", version="0.1.0")

    # Initialise database
    init_database(settings.database)

    # Initialise external clients
    _prometheus_client = PrometheusClient(
        base_url=settings.prometheus_url,
        timeout_seconds=settings.prometheus_timeout_seconds,
    )
    _grafana_client = GrafanaClient(
        base_url=settings.grafana_url,
        api_key=settings.grafana_api_key,
        org_id=settings.grafana_org_id,
    )

    logger.info(
        "Observability clients initialised",
        prometheus_url=settings.prometheus_url,
        grafana_url=settings.grafana_url,
    )

    yield

    # Shutdown
    if _slo_eval_task is not None:
        _slo_eval_task.cancel()
        try:
            await _slo_eval_task
        except asyncio.CancelledError:
            pass

    await _prometheus_client.close()
    await _grafana_client.close()
    logger.info("AumOS Observability service shut down")


app = create_app(
    service_name="aumos-observability",
    version="0.1.0",
    settings=settings,
    lifespan=lifespan,
    health_checks=[
        HealthCheck(name="prometheus", check_fn=check_prometheus),
        HealthCheck(name="grafana", check_fn=check_grafana),
    ],
)

from aumos_observability.api.router import router  # noqa: E402

app.include_router(router, prefix="/api/v1")
