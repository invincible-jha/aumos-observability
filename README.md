# aumos-observability

[![CI](https://github.com/aumos-enterprise/aumos-observability/actions/workflows/ci.yml/badge.svg)](https://github.com/aumos-enterprise/aumos-observability/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/aumos-enterprise/aumos-observability/branch/main/graph/badge.svg)](https://codecov.io/gh/aumos-enterprise/aumos-observability)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

> Full-stack observability for the AumOS Enterprise AI platform — metrics, traces, logs, SLOs, and LLM-specific tracing.

## Overview

`aumos-observability` is the monitoring backbone of the AumOS Enterprise platform. It provides a unified
API for managing SLO definitions, alert rules, and Grafana dashboards, while orchestrating the collection
pipeline of metrics (Prometheus), distributed traces (Jaeger + OpenTelemetry), log aggregation (Loki),
and LLM-specific observability (Langfuse).

Every other AumOS service reports its metrics, traces, and logs through this stack. The SLO engine runs
continuous burn rate evaluations using the Google SRE multi-window alerting approach, firing both fast
(5-min) and slow (1-hr) burn rate alerts to catch rapid and gradual error budget exhaustion.

**Product:** Foundation Infrastructure (Observability Stack)
**Tier:** Foundation Infrastructure
**Phase:** 1A

## Architecture

```
aumos-common ──► aumos-observability ──► ALL AumOS repos (consume metrics/traces/logs)
aumos-proto  ──►                      ──► Prometheus    (metrics + alerting)
                                      ──► Grafana       (7 dashboards)
                                      ──► Loki          (log aggregation)
                                      ──► Jaeger        (distributed tracing)
                                      ──► Langfuse      (LLM call tracing)
                                      ──► Kafka         (observability events)
```

This service follows AumOS hexagonal architecture:

- `api/` — FastAPI routes (thin, delegates to services)
- `core/` — Business logic with no framework dependencies
- `adapters/` — External integrations (PostgreSQL, Prometheus, Grafana, Loki, Langfuse, Kafka)

## The 7 Pre-Built Grafana Dashboards

All dashboards are provisioned via `POST /api/v1/dashboards/provision-defaults`:

| Dashboard | UID | Purpose |
|-----------|-----|---------|
| Infrastructure Overview | `aumos-infra-overview` | CPU, memory, pod restarts across all nodes |
| LLM Operations | `aumos-llm-ops` | Request rate, token usage, latency, error rate per model |
| Agent Workflow | `aumos-agent-workflow` | Task throughput, active agents, tool call success |
| Governance & Compliance | `aumos-governance` | Policy evaluations, violations, audit volume |
| Board / Executive | `aumos-executive` | Active tenants, SLO status, LLM spend, task completion |
| Cost Attribution | `aumos-cost-attribution` | LLM cost by tenant and model, daily trends |
| Security Posture | `aumos-security-posture` | Auth failures, RLS violations, rate limit hits |

## SLO Engine

The SLO engine implements Google SRE multi-window burn rate alerting:

- **Fast burn (5-min window)**: fires when `burn_rate >= fast_burn_threshold` (default 14.4x)
- **Slow burn (1-hr window)**: fires when `burn_rate >= slow_burn_threshold` (default 6x)
- Both windows must fire simultaneously to reduce false positives
- Burn rate formula: `burn_rate = current_error_rate / (1 - slo_target)`

SLOs store numerator and denominator PromQL queries. The engine queries Prometheus
on a configurable interval (`AUMOS_OBSERVABILITY_SLO_EVALUATION_INTERVAL_SECONDS`)
and persists burn rate snapshots to `obs_slo_budgets` for historical trending.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Access to AumOS internal PyPI for `aumos-common` and `aumos-proto`

### Local Development

```bash
# Clone the repo
git clone https://github.com/aumos-enterprise/aumos-observability.git
cd aumos-observability

# Set up environment
cp .env.example .env
# Edit .env with your local values

# Install dependencies
make install

# Start full observability stack (Prometheus, Grafana, Loki, Jaeger, OTEL Collector, Kafka, Postgres)
make docker-run

# Run the service
uvicorn aumos_observability.main:app --reload
```

The service will be available at `http://localhost:8000`.

Health check: `http://localhost:8000/live`
API docs: `http://localhost:8000/docs`

## API Reference

### Authentication

All endpoints require a Bearer JWT token:

```
Authorization: Bearer <token>
X-Tenant-ID: <tenant-uuid>
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/live` | Liveness probe |
| GET | `/ready` | Readiness probe (checks Prometheus + Grafana) |
| POST | `/api/v1/slos` | Create SLO definition |
| GET | `/api/v1/slos` | List SLOs |
| GET | `/api/v1/slos/{id}` | Get SLO |
| PUT | `/api/v1/slos/{id}` | Update SLO |
| DELETE | `/api/v1/slos/{id}` | Delete SLO |
| GET | `/api/v1/slos/{id}/burn-rate` | Get current burn rate |
| POST | `/api/v1/alerts/rules` | Create alert rule |
| GET | `/api/v1/alerts/rules` | List alert rules |
| GET | `/api/v1/alerts/rules/{id}` | Get alert rule |
| PUT | `/api/v1/alerts/rules/{id}` | Update alert rule |
| DELETE | `/api/v1/alerts/rules/{id}` | Delete alert rule |
| GET | `/api/v1/alerts/active` | List active alerts |
| POST | `/api/v1/dashboards/provision` | Provision a dashboard to Grafana |
| GET | `/api/v1/dashboards` | List provisioned dashboards |
| POST | `/api/v1/dashboards/provision-defaults` | Provision all 7 default dashboards |
| POST | `/api/v1/metrics/query` | Ad-hoc PromQL query |

Full OpenAPI spec available at `/docs` when running locally.

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `AUMOS_OBSERVABILITY_PROMETHEUS_URL` | `http://prometheus:9090` | Prometheus server URL |
| `AUMOS_OBSERVABILITY_GRAFANA_URL` | `http://grafana:3000` | Grafana server URL |
| `AUMOS_OBSERVABILITY_GRAFANA_API_KEY` | — | Grafana service account API key |
| `AUMOS_OBSERVABILITY_GRAFANA_ORG_ID` | `1` | Grafana organisation ID |
| `AUMOS_OBSERVABILITY_LOKI_URL` | `http://loki:3100` | Loki server URL |
| `AUMOS_OBSERVABILITY_LANGFUSE_URL` | `http://langfuse:3000` | Langfuse server URL |
| `AUMOS_OBSERVABILITY_LANGFUSE_PUBLIC_KEY` | — | Langfuse public API key |
| `AUMOS_OBSERVABILITY_LANGFUSE_SECRET_KEY` | — | Langfuse secret API key |
| `AUMOS_OBSERVABILITY_JAEGER_URL` | `http://jaeger:16686` | Jaeger query URL |
| `AUMOS_OBSERVABILITY_SLO_EVALUATION_INTERVAL_SECONDS` | `60` | SLO engine poll interval |
| `AUMOS_OTEL_ENDPOINT` | `otel-collector:4317` | OTEL Collector gRPC endpoint |

See `src/aumos_observability/settings.py` for all settings.

## Development

### Running Tests

```bash
# Full test suite with coverage
make test

# Fast run (stop on first failure)
make test-quick
```

### Linting and Formatting

```bash
# Check for issues
make lint

# Auto-fix formatting
make format

# Type checking
make typecheck
```

## Infrastructure Components

| Service | Port | Purpose |
|---------|------|---------|
| Prometheus | 9090 | Metrics collection + alerting |
| Grafana | 3000 | Dashboard visualisation |
| Loki | 3100 | Log aggregation |
| Jaeger | 16686 | Distributed trace UI |
| OTEL Collector | 4317 (gRPC), 4318 (HTTP) | Telemetry collection pipeline |
| Alertmanager | 9093 | Alert routing + silencing |

## Deployment

### Docker

```bash
make docker-build
make docker-run
```

### Production

Deployed via the AumOS GitOps pipeline. Helm chart in `helm/`.
Requires Prometheus Operator CRDs in the target cluster.

**Resource requirements:**
- CPU: 1 core (2 with SLO engine)
- Memory: 512MB
- Storage: ephemeral only (state in PostgreSQL + external monitoring systems)

## Related Repos

| Repo | Relationship | Description |
|------|-------------|-------------|
| [aumos-common](https://github.com/aumos-enterprise/aumos-common) | Dependency | Shared utilities, auth, database, events |
| [aumos-proto](https://github.com/aumos-enterprise/aumos-proto) | Dependency | Protobuf event schemas |
| ALL AumOS repos | Downstream | Every service reports metrics/traces/logs here |

## License

Copyright 2026 AumOS Enterprise. Licensed under the [Apache License 2.0](LICENSE).

This software must not incorporate AGPL or GPL licensed components.
See [CONTRIBUTING.md](CONTRIBUTING.md) for license compliance requirements.
