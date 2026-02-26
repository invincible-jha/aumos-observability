"""Prometheus HTTP API adapter.

Wraps the Prometheus HTTP API (v1) using httpx.AsyncClient.
Supports instant queries, range queries, alert retrieval, and target listing.
"""

from __future__ import annotations

from typing import Any

import httpx

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class PrometheusClient:
    """Async HTTP client for the Prometheus API.

    Implements IPrometheusClient from core/interfaces.py.
    All methods raise httpx.HTTPStatusError on non-2xx responses.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialise the Prometheus client.

        Args:
            base_url: Prometheus server base URL (e.g. http://prometheus:9090).
            timeout_seconds: Request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
        )

    async def query(
        self,
        promql_query: str,
        time: str | None = None,
    ) -> dict[str, Any]:
        """Execute an instant PromQL query.

        Args:
            promql_query: PromQL expression to evaluate.
            time: Optional RFC3339 or Unix timestamp; defaults to Prometheus now.

        Returns:
            Raw Prometheus API response dict (status, data).
        """
        params: dict[str, str] = {"query": promql_query}
        if time is not None:
            params["time"] = time

        response = await self._client.get("/api/v1/query", params=params)
        response.raise_for_status()
        return response.json()

    # Alias used by core/slo_engine.py
    async def instant_query(self, query: str) -> dict[str, Any]:
        """Execute an instant PromQL query (alias for query()).

        Args:
            query: PromQL expression.

        Returns:
            Raw Prometheus API response.
        """
        return await self.query(promql_query=query)

    async def query_range(
        self,
        promql_query: str,
        start: float | str,
        end: float | str,
        step: str = "60s",
    ) -> dict[str, Any]:
        """Execute a range PromQL query.

        Args:
            promql_query: PromQL expression to evaluate over the range.
            start: Range start as Unix timestamp or RFC3339 string.
            end: Range end as Unix timestamp or RFC3339 string.
            step: Step resolution (e.g. "60s", "5m").

        Returns:
            Raw Prometheus API response with result type "matrix".
        """
        response = await self._client.get(
            "/api/v1/query_range",
            params={
                "query": promql_query,
                "start": str(start),
                "end": str(end),
                "step": step,
            },
        )
        response.raise_for_status()
        return response.json()

    # Alias used by core/services.py
    async def range_query(
        self,
        query: str,
        start: float,
        end: float,
        step: str,
    ) -> dict[str, Any]:
        """Execute a range PromQL query (alias for query_range()).

        Args:
            query: PromQL expression.
            start: Range start as Unix timestamp.
            end: Range end as Unix timestamp.
            step: Step resolution string.

        Returns:
            Raw Prometheus API response.
        """
        return await self.query_range(
            promql_query=query,
            start=start,
            end=end,
            step=step,
        )

    async def get_alerts(self) -> list[dict[str, Any]]:
        """Retrieve all currently firing alerts from Prometheus.

        Returns:
            List of alert dicts from the Prometheus /api/v1/alerts endpoint.
        """
        response = await self._client.get("/api/v1/alerts")
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("alerts", [])

    async def get_targets(self) -> list[dict[str, Any]]:
        """Retrieve all configured scrape targets.

        Returns:
            List of target dicts from the Prometheus /api/v1/targets endpoint.
        """
        response = await self._client.get("/api/v1/targets")
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("activeTargets", [])

    async def health_check(self) -> bool:
        """Check if Prometheus is reachable.

        Returns:
            True if the Prometheus ready endpoint returns 200.
        """
        try:
            response = await self._client.get("/-/ready")
            return response.status_code == 200
        except Exception:
            logger.warning("Prometheus health check failed", base_url=self._base_url)
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client connection pool."""
        await self._client.aclose()
