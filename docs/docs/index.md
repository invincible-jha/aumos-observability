# AumOS Observability Stack

Full-stack observability for the AumOS enterprise AI platform — metrics, tracing, logs,
LLM call analysis, SLO management, anomaly detection, and frontend monitoring.

## Stack Components

| Component | Purpose | Port |
|-----------|---------|------|
| Prometheus | Metrics collection + alerting | 9090 |
| Alertmanager | Alert routing (PagerDuty, OpsGenie, Slack) | 9093 |
| Grafana | Dashboards, SLO tracking | 3000 |
| Loki | Log aggregation + LogQL | 3100 |
| Jaeger | Distributed tracing | 16686 |
| Langfuse | LLM call tracing + cost analysis | 3030 |
| Faro | Real User Monitoring (browser) | 12347 |
| OTEL Collector | Unified telemetry routing | 4317/4318 |

## 7 Pre-Built Dashboards

1. **Infrastructure Overview** — CPU, memory, pod restarts
2. **LLM Operations** — request rate, token usage, latency, error rate
3. **Agent Workflow** — task throughput, active instances, tool call success
4. **Governance & Compliance** — policy evaluations, violations, audit volume
5. **Board / Executive** — active tenants, SLO, spend, task completion
6. **Cost Attribution** — LLM cost by tenant and model
7. **Security Posture** — auth failures, RLS violations, rate limit hits

## New in Latest Release

- AI anomaly detection on LLM latency/cost via ADTK (Gap #40)
- PagerDuty, OpsGenie, Slack, Teams alert receivers (Gap #41)
- Trace-to-log correlation: Jaeger ↔ Loki linking (Gap #45)
- Grafana Faro RUM for frontend Core Web Vitals (Gap #46)
- Grafana 12 Git Sync for dashboard version control (Gap #43)
- Monthly SLO compliance PDF reports (Gap #44)

## Quick Links

- [Quickstart](quickstart.md) — first SLO in 5 minutes
- [SLO Guide](guides/first-slo.md) — multi-window burn rate alerting
- [Alert Receivers](guides/alert-receivers.md) — PagerDuty, Slack, OpsGenie
- [API Reference](api-reference.md) — all endpoints
