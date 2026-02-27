"""
Grafana dashboard JSON generator for AumOS service health.

Produces a valid Grafana v9+ dashboard JSON payload that can be imported
directly via the Grafana UI or provisioned through the Grafana HTTP API.

Dashboard layout:
- Variables: service_name, tenant_id, time range (built-in)
- Row 1: Request Rate (time series) + Active Requests (stat)
- Row 2: Error Rate (time series) + Error % (gauge)
- Row 3: Latency P50 (time series) + Latency P99 (time series)

All metric names follow the canonical aumos.* OTEL naming convention
defined in aumos_common.telemetry.metrics.
"""
from __future__ import annotations

from typing import Any


_PANEL_ID_COUNTER: list[int] = [0]


def _next_id() -> int:
    """Return a monotonically increasing panel ID."""
    _PANEL_ID_COUNTER[0] += 1
    return _PANEL_ID_COUNTER[0]


def _time_series_panel(
    panel_id: int,
    title: str,
    targets: list[dict[str, Any]],
    grid_pos: dict[str, int],
    unit: str = "short",
    description: str = "",
) -> dict[str, Any]:
    """Build a Grafana time-series panel definition.

    Args:
        panel_id: Unique panel integer ID within the dashboard.
        title: Panel display title.
        targets: List of Prometheus target objects (expr, legendFormat, refId).
        grid_pos: Grafana grid position dict with keys x, y, w, h.
        unit: Grafana unit identifier (e.g. "ms", "reqps", "short").
        description: Optional panel description shown on hover.

    Returns:
        Dictionary conforming to the Grafana panel JSON schema.
    """
    return {
        "id": panel_id,
        "title": title,
        "description": description,
        "type": "timeseries",
        "gridPos": grid_pos,
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "palette-classic"},
            },
            "overrides": [],
        },
        "options": {
            "tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {"displayMode": "table", "placement": "bottom"},
        },
    }


def _stat_panel(
    panel_id: int,
    title: str,
    targets: list[dict[str, Any]],
    grid_pos: dict[str, int],
    unit: str = "short",
    description: str = "",
) -> dict[str, Any]:
    """Build a Grafana stat (single-value) panel definition.

    Args:
        panel_id: Unique panel integer ID within the dashboard.
        title: Panel display title.
        targets: List of Prometheus target objects.
        grid_pos: Grafana grid position dict.
        unit: Grafana unit identifier.
        description: Optional panel description.

    Returns:
        Dictionary conforming to the Grafana stat panel JSON schema.
    """
    return {
        "id": panel_id,
        "title": title,
        "description": description,
        "type": "stat",
        "gridPos": grid_pos,
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 50},
                        {"color": "red", "value": 200},
                    ],
                },
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "orientation": "auto"},
    }


def _gauge_panel(
    panel_id: int,
    title: str,
    targets: list[dict[str, Any]],
    grid_pos: dict[str, int],
    unit: str = "percent",
    min_value: float = 0.0,
    max_value: float = 100.0,
    description: str = "",
) -> dict[str, Any]:
    """Build a Grafana gauge panel definition.

    Args:
        panel_id: Unique panel integer ID within the dashboard.
        title: Panel display title.
        targets: List of Prometheus target objects.
        grid_pos: Grafana grid position dict.
        unit: Grafana unit identifier.
        min_value: Minimum gauge value.
        max_value: Maximum gauge value.
        description: Optional panel description.

    Returns:
        Dictionary conforming to the Grafana gauge panel JSON schema.
    """
    return {
        "id": panel_id,
        "title": title,
        "description": description,
        "type": "gauge",
        "gridPos": grid_pos,
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": min_value,
                "max": max_value,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 2},
                        {"color": "red", "value": 5},
                    ],
                },
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
    }


class HealthDashboardGenerator:
    """Generate a Grafana dashboard JSON for AumOS service health.

    The generated dashboard can be imported directly into Grafana or
    provisioned through the DashboardService.

    Usage:
        generator = HealthDashboardGenerator()
        dashboard_json = generator.generate()
        # Pass dashboard_json to DashboardService.provision(...)
    """

    DASHBOARD_UID = "aumos-service-health"
    DASHBOARD_TITLE = "AumOS — Service Health"
    SCHEMA_VERSION = 38

    def generate(self) -> dict[str, Any]:
        """Generate the full Grafana dashboard JSON payload.

        Returns:
            Dictionary conforming to the Grafana dashboard JSON schema.
            Can be used directly as the ``dashboard_json`` field in a
            DashboardProvisionRequest.
        """
        # Reset panel ID counter for each generation call.
        _PANEL_ID_COUNTER[0] = 0

        panels = self._build_panels()

        return {
            "uid": self.DASHBOARD_UID,
            "title": self.DASHBOARD_TITLE,
            "schemaVersion": self.SCHEMA_VERSION,
            "version": 1,
            "refresh": "30s",
            "time": {"from": "now-1h", "to": "now"},
            "timepicker": {},
            "templating": {
                "list": [
                    {
                        "name": "service_name",
                        "label": "Service",
                        "type": "query",
                        "datasource": {"type": "prometheus"},
                        "query": 'label_values(aumos_requests_total, service_name)',
                        "refresh": 2,
                        "includeAll": True,
                        "multi": True,
                        "allValue": ".*",
                    },
                    {
                        "name": "tenant_id",
                        "label": "Tenant",
                        "type": "query",
                        "datasource": {"type": "prometheus"},
                        "query": 'label_values(aumos_requests_total, tenant_id)',
                        "refresh": 2,
                        "includeAll": True,
                        "multi": True,
                        "allValue": ".*",
                    },
                ],
            },
            "panels": panels,
            "annotations": {"list": []},
            "links": [],
            "tags": ["aumos", "health", "otel"],
        }

    def _build_panels(self) -> list[dict[str, Any]]:
        """Construct all dashboard panels.

        Returns:
            List of Grafana panel definition dicts in grid order.
        """
        panels: list[dict[str, Any]] = []

        # Row 1 — Request Rate and Active Requests
        panels.append(
            _time_series_panel(
                panel_id=_next_id(),
                title="Request Rate (req/s)",
                description="Total inbound requests per second, split by service and HTTP method.",
                targets=[
                    {
                        "expr": (
                            'rate(aumos_requests_total{service_name=~"$service_name",'
                            'tenant_id=~"$tenant_id"}[1m])'
                        ),
                        "legendFormat": "{{service_name}} {{method}} {{status_code}}",
                        "refId": "A",
                    }
                ],
                grid_pos={"x": 0, "y": 0, "w": 16, "h": 8},
                unit="reqps",
            )
        )
        panels.append(
            _stat_panel(
                panel_id=_next_id(),
                title="Active Requests",
                description="Number of requests currently being processed.",
                targets=[
                    {
                        "expr": (
                            'sum(aumos_requests_active{service_name=~"$service_name",'
                            'tenant_id=~"$tenant_id"})'
                        ),
                        "legendFormat": "Active",
                        "refId": "A",
                    }
                ],
                grid_pos={"x": 16, "y": 0, "w": 8, "h": 8},
                unit="short",
            )
        )

        # Row 2 — Error Rate and Error Percentage
        panels.append(
            _time_series_panel(
                panel_id=_next_id(),
                title="Error Rate (errors/s)",
                description="Rate of HTTP 4xx/5xx responses per second.",
                targets=[
                    {
                        "expr": (
                            'rate(aumos_errors_total{service_name=~"$service_name",'
                            'tenant_id=~"$tenant_id"}[1m])'
                        ),
                        "legendFormat": "{{service_name}} {{status_code}}",
                        "refId": "A",
                    }
                ],
                grid_pos={"x": 0, "y": 8, "w": 16, "h": 8},
                unit="reqps",
            )
        )
        panels.append(
            _gauge_panel(
                panel_id=_next_id(),
                title="Error Rate %",
                description="Percentage of requests that resulted in an error (4xx/5xx).",
                targets=[
                    {
                        "expr": (
                            '100 * sum(rate(aumos_errors_total{service_name=~"$service_name",'
                            'tenant_id=~"$tenant_id"}[5m])) / '
                            'sum(rate(aumos_requests_total{service_name=~"$service_name",'
                            'tenant_id=~"$tenant_id"}[5m]))'
                        ),
                        "legendFormat": "Error %",
                        "refId": "A",
                    }
                ],
                grid_pos={"x": 16, "y": 8, "w": 8, "h": 8},
                unit="percent",
                min_value=0.0,
                max_value=100.0,
            )
        )

        # Row 3 — Latency P50 and P99
        panels.append(
            _time_series_panel(
                panel_id=_next_id(),
                title="Latency P50 (ms)",
                description="Median request latency over 5-minute rolling window.",
                targets=[
                    {
                        "expr": (
                            'histogram_quantile(0.50, sum by (le, service_name) ('
                            'rate(aumos_request_duration_bucket{service_name=~"$service_name",'
                            'tenant_id=~"$tenant_id"}[5m])))'
                        ),
                        "legendFormat": "{{service_name}} p50",
                        "refId": "A",
                    }
                ],
                grid_pos={"x": 0, "y": 16, "w": 12, "h": 8},
                unit="ms",
            )
        )
        panels.append(
            _time_series_panel(
                panel_id=_next_id(),
                title="Latency P99 (ms)",
                description=(
                    "99th-percentile request latency over 5-minute rolling window. "
                    "SLO target: < 2000ms for aumos-llm-serving."
                ),
                targets=[
                    {
                        "expr": (
                            'histogram_quantile(0.99, sum by (le, service_name) ('
                            'rate(aumos_request_duration_bucket{service_name=~"$service_name",'
                            'tenant_id=~"$tenant_id"}[5m])))'
                        ),
                        "legendFormat": "{{service_name}} p99",
                        "refId": "A",
                    }
                ],
                grid_pos={"x": 12, "y": 16, "w": 12, "h": 8},
                unit="ms",
            )
        )

        return panels
