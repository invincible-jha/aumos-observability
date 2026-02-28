"""Alertmanager REST API adapter for managing alert receivers.

Provides methods for configuring PagerDuty, OpsGenie, Slack, Microsoft Teams,
email, and webhook alert receivers via the Alertmanager HTTP API.
"""

from __future__ import annotations

from typing import Any

import httpx

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class AlertmanagerClient:
    """Adapter for the Prometheus Alertmanager HTTP API.

    Manages receiver configuration, sends test alerts, and provides
    access to the Alertmanager status endpoint.
    """

    def __init__(self, alertmanager_url: str) -> None:
        """Initialise with Alertmanager base URL.

        Args:
            alertmanager_url: Base URL for Alertmanager (e.g., http://alertmanager:9093).
        """
        self._base_url = alertmanager_url.rstrip("/")

    async def get_receivers(self) -> list[dict[str, Any]]:
        """List all configured alert receivers.

        Returns:
            List of receiver configuration dicts.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base_url}/api/v2/receivers")
            resp.raise_for_status()
            return resp.json()

    async def send_test_alert(self, receiver_name: str, tenant_id: str) -> bool:
        """Send a test alert to a named receiver.

        Args:
            receiver_name: The Alertmanager receiver to test.
            tenant_id: Tenant context for the test alert.

        Returns:
            True if the test alert was accepted.
        """
        alert_payload = [
            {
                "labels": {
                    "alertname": "AumOSTestAlert",
                    "receiver": receiver_name,
                    "tenant_id": tenant_id,
                    "severity": "info",
                },
                "annotations": {
                    "summary": "AumOS test alert — you can safely ignore this",
                },
            }
        ]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/api/v2/alerts",
                json=alert_payload,
            )
            resp.raise_for_status()
            logger.info("test_alert_sent", receiver=receiver_name, tenant_id=tenant_id)
            return True

    async def reload_config(self) -> None:
        """Trigger a hot reload of Alertmanager configuration.

        Calls the Alertmanager reload endpoint after configuration changes.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._base_url}/-/reload")
            resp.raise_for_status()
            logger.info("alertmanager_config_reloaded")

    async def get_status(self) -> dict[str, Any]:
        """Return Alertmanager status including config and cluster info.

        Returns:
            Alertmanager status dict.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base_url}/api/v2/status")
            resp.raise_for_status()
            return resp.json()
