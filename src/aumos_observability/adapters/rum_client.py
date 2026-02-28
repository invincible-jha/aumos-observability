"""Grafana Faro RUM (Real User Monitoring) client adapter.

Provides configuration and status management for the Faro collector
deployed as a sidecar in the observability Helm chart.
"""

from __future__ import annotations

from typing import Any

import httpx

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class FaroRumClient:
    """Adapter for the Grafana Faro Real User Monitoring collector.

    Manages per-tenant application registration and provides the Faro
    collector endpoint configuration that frontend teams consume to
    initialise the Faro browser SDK.
    """

    def __init__(self, faro_collector_url: str, grafana_client: Any) -> None:
        """Initialise with Faro collector and Grafana API access.

        Args:
            faro_collector_url: Faro collector endpoint (e.g., http://faro:12347).
            grafana_client: GrafanaClient for dashboard provisioning.
        """
        self._faro_url = faro_collector_url.rstrip("/")
        self._grafana = grafana_client

    async def get_config(self, tenant_id: str, app_name: str) -> dict[str, Any]:
        """Return Faro SDK configuration for a tenant application.

        Frontend teams use this to initialise the Faro browser SDK.

        Args:
            tenant_id: Tenant requesting the RUM config.
            app_name: Frontend application name (used as Grafana app label).

        Returns:
            Dict with collector URL, application ID, and initialisation snippet.
        """
        app_id = f"{tenant_id[:8]}-{app_name}"
        return {
            "collector_url": f"{self._faro_url}/collect/{app_id}",
            "app_id": app_id,
            "app_name": app_name,
            "tenant_id": tenant_id,
            "faro_init_snippet": (
                f"faro.initializeFaro({{"
                f"url: '{self._faro_url}/collect/{app_id}', "
                f"app: {{name: '{app_name}', namespace: '{tenant_id}'}}"
                f"}})"
            ),
        }

    async def health_check(self) -> bool:
        """Check if the Faro collector is reachable.

        Returns:
            True if the collector responds to a health check.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._faro_url}/ready")
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("faro_health_check_failed", error=str(exc))
            return False
