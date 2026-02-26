"""Grafana HTTP API adapter.

Wraps the Grafana HTTP API using httpx.AsyncClient.
Supports dashboard CRUD, datasource creation, and alert notification channels.

The BUNDLED_DASHBOARDS constant exports the 7 default AumOS Grafana dashboards:
1. Infrastructure Overview
2. LLM Operations
3. Agent Workflow
4. Governance & Compliance
5. Board / Executive
6. Cost Attribution
7. Security Posture
"""

from __future__ import annotations

from typing import Any

import httpx

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class GrafanaClient:
    """Async HTTP client for the Grafana API.

    Implements IGrafanaClient from core/interfaces.py.
    Authenticates via API key header (Bearer token).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        org_id: int = 1,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialise the Grafana client.

        Args:
            base_url: Grafana server base URL (e.g. http://grafana:3000).
            api_key: Grafana service account API token.
            org_id: Grafana organisation ID.
            timeout_seconds: Request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._org_id = org_id
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-Grafana-Org-Id": str(org_id),
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
        )

    async def create_dashboard(
        self,
        dashboard_json: dict[str, Any],
        folder_uid: str | None = None,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """Create or update a dashboard in Grafana.

        Args:
            dashboard_json: Full Grafana dashboard JSON model.
            folder_uid: UID of the Grafana folder; uses default if None.
            overwrite: Whether to overwrite an existing dashboard with the same UID.

        Returns:
            Grafana API response dict with uid, slug, url, status, version.
        """
        payload: dict[str, Any] = {
            "dashboard": dashboard_json,
            "overwrite": overwrite,
        }
        if folder_uid is not None:
            payload["folderUid"] = folder_uid

        response = await self._client.post("/api/dashboards/db", json=payload)
        response.raise_for_status()
        return response.json()

    async def get_dashboard(self, uid: str) -> dict[str, Any]:
        """Retrieve a dashboard by UID.

        Args:
            uid: Grafana dashboard UID.

        Returns:
            Grafana dashboard model dict including dashboard JSON and metadata.
        """
        response = await self._client.get(f"/api/dashboards/uid/{uid}")
        response.raise_for_status()
        return response.json()

    async def list_dashboards(
        self,
        folder_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List dashboards, optionally filtered by folder.

        Args:
            folder_id: Grafana folder ID to filter by; returns all if None.

        Returns:
            List of dashboard search result dicts.
        """
        params: dict[str, Any] = {"type": "dash-db"}
        if folder_id is not None:
            params["folderIds"] = folder_id

        response = await self._client.get("/api/search", params=params)
        response.raise_for_status()
        return response.json()

    async def create_datasource(
        self,
        name: str,
        datasource_type: str,
        url: str,
        access: str = "proxy",
        is_default: bool = False,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new datasource in Grafana.

        Args:
            name: Datasource display name.
            datasource_type: Grafana type string (e.g. "prometheus", "loki").
            url: Datasource URL accessible from Grafana.
            access: Access mode — "proxy" (server-side) or "direct" (browser).
            is_default: Whether to set this as the default datasource.
            json_data: Optional additional type-specific configuration.

        Returns:
            Grafana API response dict with datasource id and uid.
        """
        payload: dict[str, Any] = {
            "name": name,
            "type": datasource_type,
            "url": url,
            "access": access,
            "isDefault": is_default,
        }
        if json_data is not None:
            payload["jsonData"] = json_data

        response = await self._client.post("/api/datasources", json=payload)
        response.raise_for_status()
        return response.json()

    async def create_alert_notification_channel(
        self,
        name: str,
        channel_type: str,
        settings: dict[str, Any],
        is_default: bool = False,
    ) -> dict[str, Any]:
        """Create an alert notification channel (contact point).

        Args:
            name: Channel display name.
            channel_type: Grafana type string (e.g. "slack", "email", "pagerduty").
            settings: Channel-specific settings dict.
            is_default: Whether to send all unmatched alerts to this channel.

        Returns:
            Grafana API response dict with channel id.
        """
        payload: dict[str, Any] = {
            "name": name,
            "type": channel_type,
            "settings": settings,
            "isDefault": is_default,
        }

        response = await self._client.post("/api/alert-notifications", json=payload)
        response.raise_for_status()
        return response.json()

    async def provision_dashboard(
        self,
        dashboard_json: dict[str, Any],
        folder_name: str,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """Provision a dashboard, creating the folder if it does not exist.

        Implements IGrafanaClient.provision_dashboard for use by DashboardService.

        Args:
            dashboard_json: Full Grafana dashboard JSON model.
            folder_name: Human-readable folder name (created if absent).
            overwrite: Whether to overwrite on UID collision.

        Returns:
            Grafana API response dict.
        """
        folder_uid = await self._ensure_folder(folder_name)
        return await self.create_dashboard(
            dashboard_json=dashboard_json,
            folder_uid=folder_uid,
            overwrite=overwrite,
        )

    async def _ensure_folder(self, folder_name: str) -> str:
        """Get or create a Grafana folder by name.

        Args:
            folder_name: Display name of the folder.

        Returns:
            UID of the existing or newly created folder.
        """
        # Search existing folders
        response = await self._client.get("/api/folders")
        if response.status_code == 200:
            folders = response.json()
            for folder in folders:
                if folder.get("title") == folder_name:
                    return str(folder["uid"])

        # Create folder if not found
        create_response = await self._client.post(
            "/api/folders",
            json={"title": folder_name},
        )
        create_response.raise_for_status()
        return str(create_response.json()["uid"])

    async def health_check(self) -> bool:
        """Check if Grafana is reachable.

        Returns:
            True if the Grafana health endpoint returns 200.
        """
        try:
            response = await self._client.get("/api/health")
            return response.status_code == 200
        except Exception:
            logger.warning("Grafana health check failed", base_url=self._base_url)
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client connection pool."""
        await self._client.aclose()


# ─────────────────────────────────────────────
# Bundled AumOS dashboards
# ─────────────────────────────────────────────

BUNDLED_DASHBOARDS: dict[str, dict[str, Any]] = {
    "Infrastructure Overview": {
        "uid": "aumos-infra-overview",
        "title": "AumOS Infrastructure Overview",
        "tags": ["aumos", "infrastructure"],
        "schemaVersion": 38,
        "version": 1,
        "panels": [
            {
                "id": 1,
                "title": "CPU Usage by Node",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "100 - (avg by(node) (rate(node_cpu_seconds_total{mode='idle'}[5m])) * 100)",
                        "legendFormat": "{{node}}",
                    }
                ],
            },
            {
                "id": 2,
                "title": "Memory Usage by Node",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                "targets": [
                    {
                        "expr": "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
                        "legendFormat": "{{instance}}",
                    }
                ],
            },
            {
                "id": 3,
                "title": "Pod Restart Count",
                "type": "stat",
                "gridPos": {"h": 4, "w": 6, "x": 0, "y": 8},
                "targets": [
                    {
                        "expr": "sum(kube_pod_container_status_restarts_total)",
                        "legendFormat": "Restarts",
                    }
                ],
            },
        ],
    },
    "LLM Operations": {
        "uid": "aumos-llm-ops",
        "title": "AumOS LLM Operations",
        "tags": ["aumos", "llm", "ai"],
        "schemaVersion": 38,
        "version": 1,
        "panels": [
            {
                "id": 1,
                "title": "LLM Request Rate",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_llm_requests_total[5m])) by (model, tenant_id)",
                        "legendFormat": "{{model}} / {{tenant_id}}",
                    }
                ],
            },
            {
                "id": 2,
                "title": "Token Usage (Input + Output)",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_llm_tokens_total[5m])) by (model, type)",
                        "legendFormat": "{{model}} {{type}}",
                    }
                ],
            },
            {
                "id": 3,
                "title": "LLM P99 Latency",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                "targets": [
                    {
                        "expr": "histogram_quantile(0.99, sum(rate(aumos_llm_duration_seconds_bucket[5m])) by (le, model))",
                        "legendFormat": "p99 {{model}}",
                    }
                ],
            },
            {
                "id": 4,
                "title": "LLM Error Rate",
                "type": "stat",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_llm_errors_total[5m])) / sum(rate(aumos_llm_requests_total[5m]))",
                        "legendFormat": "Error Rate",
                    }
                ],
            },
        ],
    },
    "Agent Workflow": {
        "uid": "aumos-agent-workflow",
        "title": "AumOS Agent Workflow",
        "tags": ["aumos", "agents"],
        "schemaVersion": 38,
        "version": 1,
        "panels": [
            {
                "id": 1,
                "title": "Agent Task Throughput",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_agent_tasks_total[5m])) by (agent_type, status)",
                        "legendFormat": "{{agent_type}} / {{status}}",
                    }
                ],
            },
            {
                "id": 2,
                "title": "Active Agent Instances",
                "type": "stat",
                "gridPos": {"h": 4, "w": 6, "x": 12, "y": 0},
                "targets": [
                    {
                        "expr": "sum(aumos_agent_instances_active)",
                        "legendFormat": "Active Agents",
                    }
                ],
            },
            {
                "id": 3,
                "title": "Tool Call Success Rate",
                "type": "gauge",
                "gridPos": {"h": 4, "w": 6, "x": 18, "y": 0},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_agent_tool_calls_total{status='success'}[5m])) / sum(rate(aumos_agent_tool_calls_total[5m]))",
                        "legendFormat": "Tool Success Rate",
                    }
                ],
            },
        ],
    },
    "Governance & Compliance": {
        "uid": "aumos-governance",
        "title": "AumOS Governance & Compliance",
        "tags": ["aumos", "governance", "compliance"],
        "schemaVersion": 38,
        "version": 1,
        "panels": [
            {
                "id": 1,
                "title": "Policy Evaluation Rate",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_governance_policy_evaluations_total[5m])) by (policy, result)",
                        "legendFormat": "{{policy}} / {{result}}",
                    }
                ],
            },
            {
                "id": 2,
                "title": "Compliance Violations (24h)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 6, "x": 12, "y": 0},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_governance_violations_total[24h]))",
                        "legendFormat": "Violations",
                    }
                ],
            },
            {
                "id": 3,
                "title": "Audit Log Volume",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_audit_events_total[5m])) by (event_type)",
                        "legendFormat": "{{event_type}}",
                    }
                ],
            },
        ],
    },
    "Board / Executive": {
        "uid": "aumos-executive",
        "title": "AumOS Board / Executive Dashboard",
        "tags": ["aumos", "executive", "kpi"],
        "schemaVersion": 38,
        "version": 1,
        "panels": [
            {
                "id": 1,
                "title": "Active Tenants",
                "type": "stat",
                "gridPos": {"h": 4, "w": 4, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "count(count by (tenant_id) (aumos_api_requests_total))",
                        "legendFormat": "Active Tenants",
                    }
                ],
            },
            {
                "id": 2,
                "title": "Platform API SLO (30d)",
                "type": "gauge",
                "gridPos": {"h": 4, "w": 4, "x": 4, "y": 0},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_api_requests_total{status!~'5..'}[30d])) / sum(rate(aumos_api_requests_total[30d])) * 100",
                        "legendFormat": "Availability %",
                    }
                ],
            },
            {
                "id": 3,
                "title": "Total LLM Spend (USD, 30d)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 4, "x": 8, "y": 0},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_llm_cost_usd_total[30d]))",
                        "legendFormat": "Cost USD",
                    }
                ],
            },
            {
                "id": 4,
                "title": "Total AI Tasks Completed (30d)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 4, "x": 12, "y": 0},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_agent_tasks_total{status='completed'}[30d]))",
                        "legendFormat": "Tasks",
                    }
                ],
            },
        ],
    },
    "Cost Attribution": {
        "uid": "aumos-cost-attribution",
        "title": "AumOS Cost Attribution",
        "tags": ["aumos", "cost", "finops"],
        "schemaVersion": 38,
        "version": 1,
        "panels": [
            {
                "id": 1,
                "title": "LLM Cost by Tenant",
                "type": "piechart",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_llm_cost_usd_total[30d])) by (tenant_id)",
                        "legendFormat": "{{tenant_id}}",
                    }
                ],
            },
            {
                "id": 2,
                "title": "LLM Cost by Model",
                "type": "piechart",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_llm_cost_usd_total[30d])) by (model)",
                        "legendFormat": "{{model}}",
                    }
                ],
            },
            {
                "id": 3,
                "title": "Daily Cost Trend",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 24, "x": 0, "y": 8},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_llm_cost_usd_total[1d])) by (tenant_id)",
                        "legendFormat": "{{tenant_id}}",
                    }
                ],
            },
        ],
    },
    "Security Posture": {
        "uid": "aumos-security-posture",
        "title": "AumOS Security Posture",
        "tags": ["aumos", "security"],
        "schemaVersion": 38,
        "version": 1,
        "panels": [
            {
                "id": 1,
                "title": "Authentication Failures (1h)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_auth_failures_total[1h]))",
                        "legendFormat": "Auth Failures",
                    }
                ],
            },
            {
                "id": 2,
                "title": "Cross-Tenant Access Attempts",
                "type": "stat",
                "gridPos": {"h": 4, "w": 6, "x": 6, "y": 0},
                "targets": [
                    {
                        "expr": "sum(increase(aumos_rls_violation_attempts_total[1h]))",
                        "legendFormat": "RLS Violations",
                    }
                ],
            },
            {
                "id": 3,
                "title": "Rate Limit Hits by Tenant",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 24, "x": 0, "y": 4},
                "targets": [
                    {
                        "expr": "sum(rate(aumos_rate_limit_hits_total[5m])) by (tenant_id)",
                        "legendFormat": "{{tenant_id}}",
                    }
                ],
            },
        ],
    },
}
