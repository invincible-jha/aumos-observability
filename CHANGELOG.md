# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project scaffolding for aumos-observability
- Alert rule management API (CRUD + active alert listing)
- Dashboard management API with 7 pre-built Grafana dashboards
- SLO engine with Google SRE multi-window burn rate alerting
- Prometheus adapter for instant and range PromQL queries
- Grafana adapter for dashboard provisioning and datasource management
- Langfuse LLM tracing adapter (traces, spans, generations, scores)
- Loki log aggregation adapter (query, push, label listing)
- SQLAlchemy repositories for all obs_ tables
- Kafka event publisher (ObservabilityEventPublisher)
- Hexagonal architecture (api/core/adapters layers)
- Full docker-compose.dev.yml with all 7 infrastructure services
- Standard AumOS deliverables (CLAUDE.md, README, pyproject.toml, Dockerfile, etc.)
