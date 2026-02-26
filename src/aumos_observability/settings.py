"""Service-specific settings extending AumOS base config for the Observability Stack."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from aumos_common.config import AumOSSettings


class Settings(AumOSSettings):
    """Observability service settings.

    All standard AumOS settings inherited from AumOSSettings.
    Observability-specific settings use AUMOS_OBSERVABILITY_ prefix.
    """

    service_name: str = "aumos-observability"

    # Prometheus
    prometheus_url: str = Field(
        default="http://prometheus:9090",
        description="Prometheus server base URL",
    )
    prometheus_timeout_seconds: float = Field(
        default=30.0,
        description="Prometheus API request timeout",
    )

    # Grafana
    grafana_url: str = Field(
        default="http://grafana:3000",
        description="Grafana server base URL",
    )
    grafana_api_key: str = Field(
        default="",
        description="Grafana API key for dashboard provisioning",
    )
    grafana_org_id: int = Field(
        default=1,
        description="Grafana organisation ID",
    )

    # Langfuse
    langfuse_url: str = Field(
        default="http://langfuse:3000",
        description="Langfuse server base URL",
    )
    langfuse_public_key: str = Field(
        default="",
        description="Langfuse public API key",
    )
    langfuse_secret_key: str = Field(
        default="",
        description="Langfuse secret API key",
    )

    # Loki
    loki_url: str = Field(
        default="http://loki:3100",
        description="Loki server base URL",
    )

    # Jaeger
    jaeger_url: str = Field(
        default="http://jaeger:16686",
        description="Jaeger query server base URL",
    )

    # SLO Engine
    slo_evaluation_interval_seconds: int = Field(
        default=60,
        description="How often the SLO engine evaluates burn rates",
    )
    slo_fast_burn_window_minutes: int = Field(
        default=5,
        description="Fast burn alerting window in minutes",
    )
    slo_slow_burn_window_minutes: int = Field(
        default=60,
        description="Slow burn alerting window in minutes",
    )

    # Alert management
    alertmanager_url: str = Field(
        default="http://alertmanager:9093",
        description="Alertmanager base URL",
    )

    # OTEL Collector
    otel_collector_grpc_endpoint: str = Field(
        default="otel-collector:4317",
        description="OTEL Collector gRPC endpoint",
    )
    otel_collector_http_endpoint: str = Field(
        default="http://otel-collector:4318",
        description="OTEL Collector HTTP endpoint",
    )

    model_config = SettingsConfigDict(env_prefix="AUMOS_OBSERVABILITY_")
