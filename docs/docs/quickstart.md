# Quickstart: First SLO in 5 Minutes

Create your first SLO (Service Level Objective) and configure a burn rate alert.

## Prerequisites

- AumOS platform running
- Auth token with `PRIVILEGED` (privilege >= 3) access
- Your service exposing `/metrics` on port 8000

## Step 1: Create an SLO

```python
import httpx

BASE = "http://aumos-observability:8000/api/v1"
HEADERS = {"Authorization": "Bearer <token>", "X-Tenant-ID": "<tenant-id>"}

slo = httpx.post(f"{BASE}/slos", headers=HEADERS, json={
    "name": "API Availability",
    "description": "99.9% availability SLO for the customer API",
    "slo_target": 0.999,
    "error_budget_minutes": 43,  # 43 min/month at 99.9%
    "prometheus_query": 'sum(rate(http_requests_total{job="api",code!~"5.."}[5m])) / sum(rate(http_requests_total{job="api"}[5m]))',
    "window_days": 30
})
print(slo.json())
```

## Step 2: Check Burn Rate

```python
slo_id = slo.json()["id"]
burn = httpx.get(f"{BASE}/slos/{slo_id}/burn-rate", headers=HEADERS)
print(f"Current burn rate: {burn.json()['burn_rate']}x")
print(f"Error budget remaining: {burn.json()['error_budget_remaining_pct']}%")
```

## Step 3: Configure a Slack Alert Receiver

```python
receiver = httpx.post(f"{BASE}/alert-receivers", headers=HEADERS, json={
    "receiver_type": "slack",
    "name": "engineering-alerts",
    "webhook_url_vault_path": "secrets/data/tenants/<id>/slack-webhook",
    "channel": "#platform-alerts"
})
```

## Step 4: Send a Test Alert

```python
httpx.post(
    f"{BASE}/alert-receivers/{receiver.json()['id']}/test",
    headers=HEADERS
)
# Check #platform-alerts channel for the test notification
```

## Next Steps

- [Dashboard Guide](guides/dashboards.md) — explore the 7 pre-built Grafana dashboards
- [LLM Tracing](guides/llm-tracing.md) — trace every LLM call with Langfuse
- [Anomaly Detection](guides/anomaly-detection.md) — automated spike detection on LLM costs
