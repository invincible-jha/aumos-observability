"""Loki log aggregation adapter.

Wraps the Loki HTTP API using httpx.AsyncClient.
Supports LogQL queries, log pushing, and label introspection.
"""

from __future__ import annotations

from typing import Any

import httpx

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class LokiClient:
    """Async HTTP client for the Loki log aggregation API.

    Provides LogQL query execution, log ingestion, and label listing.
    Uses the Loki HTTP API v1.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        auth: tuple[str, str] | None = None,
    ) -> None:
        """Initialise the Loki client.

        Args:
            base_url: Loki server base URL (e.g. http://loki:3100).
            timeout_seconds: Request timeout in seconds.
            auth: Optional (username, password) tuple for basic auth.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
            auth=auth,
        )

    async def query_logs(
        self,
        logql_query: str,
        limit: int = 100,
        start: int | None = None,
        end: int | None = None,
        direction: str = "backward",
    ) -> list[dict[str, Any]]:
        """Execute a LogQL query against Loki.

        Supports both log and metric queries via the /loki/api/v1/query_range endpoint.

        Args:
            logql_query: LogQL expression (e.g. '{job="aumos"} |= "error"').
            limit: Maximum number of log lines to return.
            start: Start timestamp as Unix nanoseconds.
            end: End timestamp as Unix nanoseconds.
            direction: Log ordering — "backward" (newest first) or "forward".

        Returns:
            List of stream result dicts with keys: stream (labels) and values (entries).
        """
        params: dict[str, Any] = {
            "query": logql_query,
            "limit": limit,
            "direction": direction,
        }
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end

        response = await self._client.get("/loki/api/v1/query_range", params=params)
        response.raise_for_status()

        data = response.json()
        return data.get("data", {}).get("result", [])

    async def push_logs(
        self,
        streams: list[dict[str, Any]],
    ) -> None:
        """Push log entries to Loki.

        Args:
            streams: List of stream dicts, each with:
                - stream (dict[str, str]): Label set for the stream.
                - values (list[list[str, str]]): List of [timestamp_ns, log_line] pairs.

        Example::
            await loki.push_logs([
                {
                    "stream": {"job": "aumos-observability", "level": "info"},
                    "values": [["1700000000000000000", "Service started"]],
                }
            ])
        """
        payload = {"streams": streams}
        response = await self._client.post("/loki/api/v1/push", json=payload)
        response.raise_for_status()
        logger.debug("Pushed log streams to Loki", stream_count=len(streams))

    async def get_labels(self) -> list[str]:
        """Retrieve all label names from Loki.

        Returns:
            List of label name strings (e.g. ["job", "level", "tenant_id"]).
        """
        response = await self._client.get("/loki/api/v1/labels")
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])

    async def get_label_values(self, label: str) -> list[str]:
        """Retrieve all values for a specific label.

        Args:
            label: Label name to fetch values for (e.g. "job").

        Returns:
            List of string values for the label.
        """
        response = await self._client.get(f"/loki/api/v1/label/{label}/values")
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])

    async def health_check(self) -> bool:
        """Check if Loki is reachable.

        Returns:
            True if the Loki ready endpoint returns 200.
        """
        try:
            response = await self._client.get("/ready")
            return response.status_code == 200
        except Exception:
            logger.warning("Loki health check failed", base_url=self._base_url)
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client connection pool."""
        await self._client.aclose()
