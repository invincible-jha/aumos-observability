# CLAUDE.md — AumOS Observability Stack

## Project Overview

AumOS Enterprise is a composable enterprise AI platform with 9 products + 2 services
across 62 repositories. This repo (`aumos-observability`) is part of **Foundation Infrastructure**:
shared observability and monitoring services consumed by every AumOS service.

**Release Tier:** A (Fully Open)
**Product Mapping:** Foundation Service — Observability Stack
**Phase:** 1A (Months 1-4)

## Repo Purpose

Provides full-stack observability for the AumOS platform: metrics via Prometheus,
distributed tracing via Jaeger + OTEL, log aggregation via Loki, LLM-specific tracing
via Langfuse, and SLO management with Google SRE-style multi-window burn rate alerting.
Every AumOS service reports metrics, traces, and logs through this stack.

## Architecture Position

```
aumos-common ──► aumos-observability ──► ALL repos (every service reports metrics/traces/logs)
aumos-proto  ──►                      ──► aumos-event-bus (publishes observability events)
                                      ──► Prometheus (PromQL queries + alerting)
                                      ──► Grafana (7 pre-built dashboards)
                                      ──► Loki (log aggregation)
                                      ──► Jaeger (distributed tracing)
                                      ──► Langfuse (LLM call tracing)
```

**Upstream dependencies (this repo IMPORTS from):**
- `aumos-common` — auth, database, events, errors, config, health, pagination
- `aumos-proto` — Protobuf message definitions for Kafka events

**Downstream dependents (other repos IMPORT from this):**
- ALL AumOS repos — every service sends metrics, traces, and logs to this stack

## Tech Stack (DO NOT DEVIATE)

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | Runtime |
| FastAPI | 0.110+ | REST API framework |
| SQLAlchemy | 2.0+ (async) | Database ORM |
| asyncpg | 0.29+ | PostgreSQL async driver |
| Pydantic | 2.6+ | Data validation, settings, API schemas |
| confluent-kafka | 2.3+ | Kafka producer/consumer |
| structlog | 24.1+ | Structured JSON logging |
| OpenTelemetry | 1.23+ | Distributed tracing |
| pytest | 8.0+ | Testing framework |
| ruff | 0.3+ | Linting and formatting |
| mypy | 1.8+ | Type checking |
| httpx | 0.27+ | Async HTTP client for Prometheus, Grafana, Loki, Langfuse |
| prometheus-client | 0.20+ | Prometheus metrics SDK |

## Coding Standards

### ABSOLUTE RULES (violations will break integration with other repos)

1. **Import aumos-common, never reimplement.** If aumos-common provides it, use it.
   ```python
   # CORRECT
   from aumos_common.auth import get_current_tenant, get_current_user
   from aumos_common.database import get_db_session, Base, AumOSModel, BaseRepository
   from aumos_common.events import EventPublisher, Topics
   from aumos_common.errors import NotFoundError, ErrorCode
   from aumos_common.config import AumOSSettings
   from aumos_common.health import create_health_router
   from aumos_common.pagination import PageRequest, PageResponse, paginate
   from aumos_common.app import create_app
   ```

2. **Type hints on EVERY function.** No exceptions.

3. **Pydantic models for ALL API inputs/outputs.** Never return raw dicts.

4. **RLS tenant isolation via aumos-common.** Never write raw SQL that bypasses RLS.

5. **Structured logging via structlog.** Never use print() or logging.getLogger().

6. **Publish domain events to Kafka after state changes.**

7. **Async by default.** All I/O operations must be async.

8. **Google-style docstrings** on all public classes and functions.

### Style Rules

- Max line length: **120 characters**
- Import order: stdlib → third-party → aumos-common → local
- Linter: `ruff` (select E, W, F, I, N, UP, ANN, B, A, COM, C4, PT, RUF)
- Type checker: `mypy` strict mode
- Formatter: `ruff format`

### File Structure Convention

```
src/aumos_observability/
├── __init__.py
├── main.py                   # FastAPI app entry point
├── settings.py               # Extends AumOSSettings — AUMOS_OBSERVABILITY_ prefix
├── api/
│   ├── __init__.py
│   ├── router.py             # Aggregates alert, dashboard, slo, metrics routes
│   ├── schemas.py            # Pydantic schemas for all API types
│   ├── alert_routes.py       # Alert rule CRUD + active alert listing
│   ├── dashboard_routes.py   # Dashboard provisioning endpoints
│   └── slo_routes.py         # SLO CRUD + burn rate endpoint
├── core/
│   ├── __init__.py
│   ├── models.py             # SQLAlchemy models — obs_ prefix
│   ├── services.py           # SLOService, AlertService, DashboardService, MetricsService
│   ├── interfaces.py         # Protocol classes for all adapters
│   └── slo_engine.py         # Google SRE burn rate calculation engine
└── adapters/
    ├── __init__.py
    ├── repositories.py       # SQLAlchemy repos for all obs_ tables
    ├── prometheus_client.py  # Prometheus HTTP API adapter
    ├── grafana_client.py     # Grafana HTTP API adapter + 7 bundled dashboards
    ├── langfuse_client.py    # Langfuse LLM tracing adapter
    ├── loki_client.py        # Loki log aggregation adapter
    └── kafka.py              # ObservabilityEventPublisher
```

## API Conventions

- All endpoints under `/api/v1/` prefix
- Auth: Bearer JWT token (validated by aumos-common)
- Tenant: `X-Tenant-ID` header (set by auth middleware)
- Pagination: `?page=1&page_size=20`
- Errors: Standard `ErrorResponse` from aumos-common
- Content-Type: `application/json` (always)

## Database Conventions

- Table prefix: `obs_` (e.g., `obs_alert_rules`, `obs_slo_definitions`)
- ALL tenant-scoped tables: extend `AumOSModel` (gets id, tenant_id, created_at, updated_at)
- RLS policy on every tenant table (created in migration)
- Migration naming: `{timestamp}_obs_{description}.py`

## Kafka Conventions

- Publish events via `ObservabilityEventPublisher` (wraps aumos-common EventPublisher)
- Use `Topics.OBSERVABILITY_EVENTS` for all observability domain events
- Always include `tenant_id` and `correlation_id` in events

## Repo-Specific Context

### SLO Engine
The SLO engine uses Google SRE multi-window burn rate alerting:
- **Fast burn** (5-min window): detects rapid error budget exhaustion (default 14.4x)
- **Slow burn** (1-hr window): detects gradual erosion (default 6x)
- Both windows must fire simultaneously to avoid false positives
- Formula: `burn_rate = current_error_rate / (1 - slo_target)`

### The 7 Bundled Grafana Dashboards
All dashboards are defined in `adapters/grafana_client.py:BUNDLED_DASHBOARDS`:
1. **Infrastructure Overview** — CPU, memory, pod restarts
2. **LLM Operations** — request rate, token usage, latency, error rate
3. **Agent Workflow** — task throughput, active instances, tool call success
4. **Governance & Compliance** — policy evaluations, violations, audit volume
5. **Board / Executive** — active tenants, SLO, spend, task completion
6. **Cost Attribution** — LLM cost by tenant and model, daily trends
7. **Security Posture** — auth failures, RLS violations, rate limit hits

### OpenTelemetry Collector
The OTEL Collector receives traces from all AumOS services and routes them to Jaeger.
Configuration is in `otel-config/`. Services send traces to `otel-collector:4317` (gRPC)
or `otel-collector:4318` (HTTP).

### Prometheus + Alertmanager
Prometheus scrapes all AumOS services on port 8000 `/metrics`.
Alert rules are stored in `prometheus-config/rules/`. Custom per-tenant rules
are managed via the alert rules API and synced to Prometheus.

### Langfuse
Langfuse traces every LLM call in the platform. The adapter uses the Langfuse
v1 REST ingestion API with batch events. Public and secret keys are per-deployment.
The Langfuse host is configured via `AUMOS_OBSERVABILITY_LANGFUSE_URL`.

### Loki + Log Aggregation
Loki receives structured JSON logs from all AumOS services via the OTEL Collector.
LogQL queries allow tenant-scoped log search and alerting.

## Environment Variable Prefix

`AUMOS_OBSERVABILITY_` — see `settings.py` for all variables.

Key variables:
- `AUMOS_OBSERVABILITY_PROMETHEUS_URL` — Prometheus base URL
- `AUMOS_OBSERVABILITY_GRAFANA_URL` — Grafana base URL
- `AUMOS_OBSERVABILITY_GRAFANA_API_KEY` — Grafana service account token
- `AUMOS_OBSERVABILITY_LOKI_URL` — Loki base URL
- `AUMOS_OBSERVABILITY_LANGFUSE_URL` — Langfuse base URL
- `AUMOS_OBSERVABILITY_LANGFUSE_PUBLIC_KEY` — Langfuse public key
- `AUMOS_OBSERVABILITY_LANGFUSE_SECRET_KEY` — Langfuse secret key
- `AUMOS_OTEL_ENDPOINT` — OTEL Collector endpoint (used by all services)

## What Claude Code Should NOT Do

1. **Do NOT reimplement anything in aumos-common.**
2. **Do NOT use print().** Use `get_logger(__name__)`.
3. **Do NOT return raw dicts from API endpoints.** Use Pydantic models.
4. **Do NOT write raw SQL.** Use SQLAlchemy ORM with repositories.
5. **Do NOT hardcode configuration.** Use Pydantic Settings with env vars.
6. **Do NOT skip type hints.** Every function signature must be typed.
7. **Do NOT import AGPL/GPL licensed packages** without explicit approval.
8. **Do NOT put business logic in API routes.** Routes call services.
9. **Do NOT bypass RLS.** The `list_active` method in SLODefinitionRepository
   is the only intentional RLS bypass — it's for the background SLO engine only.
10. **Do NOT hardcode Prometheus/Grafana URLs.** Always use settings.
