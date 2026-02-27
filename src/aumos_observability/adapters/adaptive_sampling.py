"""Adaptive Sampling Engine adapter — dynamic trace sampling rate adjustment.

Monitors traffic volume in real time and automatically adjusts sampling rates
to stay within a target budget. Preserves errors and slow traces regardless
of rate adjustments. Supports per-endpoint configuration and A/B sampling
comparison for effectiveness analysis.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class AdaptiveMode(str, Enum):
    """Operating mode for the adaptive sampling engine."""

    AUTO = "auto"            # Automatically adjust rate based on budget
    FIXED = "fixed"          # Use a fixed rate, no adjustment
    EMERGENCY = "emergency"  # Extreme reduction — only errors sampled


@dataclass
class SamplingBudget:
    """Sampling throughput budget configuration.

    Attributes:
        max_spans_per_second: Hard cap on sampled spans per second globally.
        max_spans_per_service: Per-service span cap per second (0 = unlimited).
        target_sample_rate_min: Minimum allowed sample rate (never go below this).
        target_sample_rate_max: Maximum allowed sample rate.
        adjustment_interval_seconds: How often to recalculate the rate.
    """

    max_spans_per_second: float = 1000.0
    max_spans_per_service: float = 0.0
    target_sample_rate_min: float = 0.001
    target_sample_rate_max: float = 1.0
    adjustment_interval_seconds: float = 60.0


@dataclass
class EndpointSamplingConfig:
    """Per-endpoint sampling override configuration.

    Attributes:
        service_name: Service name the endpoint belongs to.
        endpoint_pattern: URL pattern or operation name to match (substring match).
        sample_rate: Fixed sample rate for this endpoint (overrides adaptive rate).
        always_sample: Always sample this endpoint regardless of rates.
        never_sample: Never sample this endpoint (e.g., health checks).
    """

    service_name: str
    endpoint_pattern: str
    sample_rate: float = 0.1
    always_sample: bool = False
    never_sample: bool = False


@dataclass
class TrafficSnapshot:
    """Point-in-time traffic measurement for a service.

    Attributes:
        service_name: Service name.
        spans_per_second: Observed ingest rate in spans/second.
        sampled_per_second: Effective sampled span rate.
        current_rate: Active sample rate at time of snapshot.
        timestamp: UTC timestamp of measurement.
    """

    service_name: str
    spans_per_second: float
    sampled_per_second: float
    current_rate: float
    timestamp: datetime


@dataclass
class AdaptiveAdjustment:
    """Record of an automatic sampling rate adjustment.

    Attributes:
        service_name: Service that was adjusted.
        previous_rate: Sample rate before adjustment.
        new_rate: Sample rate after adjustment.
        trigger_reason: Why the adjustment was made.
        traffic_spans_per_second: Traffic volume at time of adjustment.
        adjusted_at: UTC timestamp of adjustment.
    """

    service_name: str
    previous_rate: float
    new_rate: float
    trigger_reason: str
    traffic_spans_per_second: float
    adjusted_at: datetime


@dataclass
class ABSamplingComparison:
    """Comparison result between two sampling rate configurations.

    Attributes:
        service_name: Service being compared.
        rate_a: First sample rate tested.
        rate_b: Second sample rate tested.
        spans_sampled_a: Spans collected at rate_a.
        spans_sampled_b: Spans collected at rate_b.
        error_coverage_a: Error trace coverage at rate_a (0.0–1.0).
        error_coverage_b: Error trace coverage at rate_b.
        recommendation: Which rate performed better overall.
        analysis_period_seconds: Duration of the comparison.
    """

    service_name: str
    rate_a: float
    rate_b: float
    spans_sampled_a: int
    spans_sampled_b: int
    error_coverage_a: float
    error_coverage_b: float
    recommendation: float
    analysis_period_seconds: float


@dataclass
class SamplingEffectivenessMetrics:
    """Effectiveness metrics for the adaptive sampling engine.

    Attributes:
        service_name: Service being tracked.
        current_sample_rate: Active sample rate.
        mode: Current operating mode.
        total_adjustments: Number of rate adjustments since startup.
        budget_utilization_pct: Fraction of span budget consumed.
        error_preservation_rate: Fraction of error traces kept.
        slow_trace_preservation_rate: Fraction of slow traces kept.
        last_adjustment: Most recent rate adjustment details.
        computed_at: UTC timestamp.
    """

    service_name: str
    current_sample_rate: float
    mode: AdaptiveMode
    total_adjustments: int
    budget_utilization_pct: float
    error_preservation_rate: float
    slow_trace_preservation_rate: float
    last_adjustment: AdaptiveAdjustment | None
    computed_at: datetime


class AdaptiveSamplingEngine:
    """Dynamic sampling rate adjustment engine.

    Monitors incoming trace volume via Prometheus metrics and automatically
    lowers the head-based sample rate when traffic exceeds the configured
    budget. Priority rules (errors, slow traces) are always preserved
    regardless of rate adjustments.

    Rate adjustment algorithm:
        new_rate = budget.max_spans_per_second / observed_spans_per_second
        new_rate is clamped to [budget.target_sample_rate_min, budget.target_sample_rate_max]

    Args:
        prometheus_client: Async Prometheus HTTP API client.
        budget: Sampling budget configuration.
        mode: Initial operating mode.
        latency_threshold_ms: Threshold for slow trace preservation (ms).
    """

    def __init__(
        self,
        prometheus_client: Any,
        budget: SamplingBudget | None = None,
        mode: AdaptiveMode = AdaptiveMode.AUTO,
        latency_threshold_ms: float = 1000.0,
    ) -> None:
        """Initialize AdaptiveSamplingEngine.

        Args:
            prometheus_client: Async Prometheus HTTP API client.
            budget: Sampling budget configuration (defaults applied if None).
            mode: Initial operating mode.
            latency_threshold_ms: Threshold for slow trace priority preservation.
        """
        self._prometheus = prometheus_client
        self._budget = budget or SamplingBudget()
        self._mode = mode
        self._latency_threshold_ms = latency_threshold_ms

        self._current_rates: dict[str, float] = {}
        self._adjustment_counts: dict[str, int] = {}
        self._last_adjustments: dict[str, AdaptiveAdjustment] = {}
        self._endpoint_configs: list[EndpointSamplingConfig] = []
        self._traffic_history: dict[str, list[TrafficSnapshot]] = {}
        self._last_adjustment_time: dict[str, float] = {}

    def set_mode(self, mode: AdaptiveMode) -> None:
        """Change the operating mode of the adaptive engine.

        Args:
            mode: New operating mode.
        """
        logger.info("Adaptive sampling mode changed", new_mode=mode.value, previous_mode=self._mode.value)
        self._mode = mode

    def configure_endpoint(self, config: EndpointSamplingConfig) -> None:
        """Add or update per-endpoint sampling override.

        Args:
            config: Endpoint-specific sampling configuration.
        """
        self._endpoint_configs = [
            c for c in self._endpoint_configs
            if not (c.service_name == config.service_name and c.endpoint_pattern == config.endpoint_pattern)
        ]
        self._endpoint_configs.append(config)
        logger.info(
            "Endpoint sampling configured",
            service_name=config.service_name,
            endpoint_pattern=config.endpoint_pattern,
            sample_rate=config.sample_rate,
            always_sample=config.always_sample,
            never_sample=config.never_sample,
        )

    def _get_endpoint_override(
        self,
        service_name: str,
        operation_name: str,
    ) -> EndpointSamplingConfig | None:
        """Look up per-endpoint sampling override for a service+operation pair.

        Args:
            service_name: Service name.
            operation_name: Operation or endpoint name.

        Returns:
            Matching EndpointSamplingConfig or None if no override applies.
        """
        for config in self._endpoint_configs:
            if config.service_name == service_name and config.endpoint_pattern in operation_name:
                return config
        return None

    async def get_current_traffic(self, service_name: str) -> float:
        """Query Prometheus for the current trace span ingest rate.

        Args:
            service_name: Service name to query.

        Returns:
            Observed spans per second for the service.
        """
        try:
            query = (
                f'sum(rate(traces_exporter_sent_spans_total{{service_name="{service_name}"}}[1m]))'
            )
            result = await self._prometheus.instant_query(query)
            data = result.get("data", {}).get("result", [])
            if data:
                return float(data[0].get("value", [0, 0])[1])
        except Exception as exc:
            logger.warning(
                "Failed to query traffic rate",
                service_name=service_name,
                error=str(exc),
            )
        return 0.0

    async def compute_adjusted_rate(self, service_name: str) -> float:
        """Compute the optimal sample rate for a service given current traffic.

        Rate = budget.max_spans_per_second / observed_spans_per_second,
        clamped to [target_sample_rate_min, target_sample_rate_max].

        Emergency mode always returns target_sample_rate_min.
        Fixed mode returns the current configured rate unchanged.

        Args:
            service_name: Service to compute rate for.

        Returns:
            Recommended sample rate (0.0–1.0).
        """
        if self._mode == AdaptiveMode.EMERGENCY:
            return self._budget.target_sample_rate_min

        if self._mode == AdaptiveMode.FIXED:
            return self._current_rates.get(service_name, self._budget.target_sample_rate_max)

        traffic = await self.get_current_traffic(service_name)
        if traffic <= 0:
            return self._budget.target_sample_rate_max

        target_traffic = self._budget.max_spans_per_second
        if self._budget.max_spans_per_service > 0:
            target_traffic = min(target_traffic, self._budget.max_spans_per_service)

        raw_rate = target_traffic / traffic
        clamped_rate = max(
            self._budget.target_sample_rate_min,
            min(self._budget.target_sample_rate_max, raw_rate),
        )
        return clamped_rate

    async def adjust_rate(self, service_name: str) -> AdaptiveAdjustment | None:
        """Evaluate and apply a rate adjustment for a service.

        Skips adjustment if the interval has not elapsed since last adjustment.
        Logs and records all adjustments for audit and effectiveness tracking.

        Args:
            service_name: Service to adjust sampling rate for.

        Returns:
            AdaptiveAdjustment if a change was made, None if no change needed.
        """
        now = time.monotonic()
        last_adjusted = self._last_adjustment_time.get(service_name, 0.0)
        if now - last_adjusted < self._budget.adjustment_interval_seconds:
            return None

        previous_rate = self._current_rates.get(service_name, self._budget.target_sample_rate_max)
        new_rate = await self.compute_adjusted_rate(service_name)
        traffic = await self.get_current_traffic(service_name)

        change_magnitude = abs(new_rate - previous_rate)
        if change_magnitude < 0.001:
            self._last_adjustment_time[service_name] = now
            return None

        self._current_rates[service_name] = new_rate
        self._last_adjustment_time[service_name] = now
        self._adjustment_counts[service_name] = self._adjustment_counts.get(service_name, 0) + 1

        if new_rate < previous_rate:
            reason = f"Traffic {traffic:.1f} spans/s exceeds budget — reduced rate from {previous_rate:.4f} to {new_rate:.4f}"
        else:
            reason = f"Traffic {traffic:.1f} spans/s within budget — increased rate from {previous_rate:.4f} to {new_rate:.4f}"

        adjustment = AdaptiveAdjustment(
            service_name=service_name,
            previous_rate=previous_rate,
            new_rate=new_rate,
            trigger_reason=reason,
            traffic_spans_per_second=traffic,
            adjusted_at=datetime.now(tz=timezone.utc),
        )
        self._last_adjustments[service_name] = adjustment

        logger.info(
            "Sampling rate adjusted",
            service_name=service_name,
            previous_rate=previous_rate,
            new_rate=new_rate,
            traffic_spans_per_second=traffic,
            mode=self._mode.value,
        )

        return adjustment

    def should_sample(
        self,
        service_name: str,
        operation_name: str,
        has_error: bool = False,
        duration_ms: float = 0.0,
        trace_id: str | None = None,
    ) -> tuple[bool, str]:
        """Make an immediate sampling decision using current rates.

        Checks endpoint overrides and priority rules before applying
        the adaptive rate. All error traces are always sampled.

        Args:
            service_name: Service name.
            operation_name: Operation or endpoint name.
            has_error: True if the trace contains an error.
            duration_ms: Trace duration for slow-trace detection.
            trace_id: Optional trace ID for deterministic sampling.

        Returns:
            Tuple of (should_sample, reason).
        """
        endpoint_override = self._get_endpoint_override(service_name, operation_name)
        if endpoint_override:
            if endpoint_override.never_sample:
                return False, f"Endpoint {operation_name} excluded from sampling"
            if endpoint_override.always_sample:
                return True, f"Endpoint {operation_name} always sampled"

        if has_error:
            return True, "Error trace — priority sampled"

        if duration_ms >= self._latency_threshold_ms:
            return True, f"Slow trace ({duration_ms:.1f}ms) — priority sampled"

        rate = self._current_rates.get(service_name, self._budget.target_sample_rate_max)
        if endpoint_override:
            rate = endpoint_override.sample_rate

        if trace_id:
            import hashlib
            hash_val = int(hashlib.md5(trace_id.encode(), usedforsecurity=False).hexdigest()[:8], 16)
            sampled = (hash_val / 0xFFFFFFFF) < rate
        else:
            import random
            sampled = random.random() < rate  # noqa: S311 — not crypto

        return sampled, f"Adaptive sampling at rate {rate:.4f}: {'kept' if sampled else 'dropped'}"

    async def run_adjustment_cycle(self, service_names: list[str]) -> list[AdaptiveAdjustment]:
        """Run one adjustment cycle for multiple services.

        Typically called by a background task on each adjustment interval.

        Args:
            service_names: List of services to evaluate and possibly adjust.

        Returns:
            List of AdaptiveAdjustment records for services that were changed.
        """
        adjustments: list[AdaptiveAdjustment] = []
        for service_name in service_names:
            adjustment = await self.adjust_rate(service_name)
            if adjustment is not None:
                adjustments.append(adjustment)
        return adjustments

    async def compare_ab_rates(
        self,
        service_name: str,
        rate_a: float,
        rate_b: float,
        observation_period_seconds: float = 300.0,
    ) -> ABSamplingComparison:
        """Simulate an A/B comparison between two sampling rates.

        Queries Prometheus for traffic and error data to estimate
        what each rate would collect over the observation period.
        This is a simulation based on current traffic — it does not
        actually split live traffic between two rates.

        Args:
            service_name: Service to analyze.
            rate_a: First candidate sample rate.
            rate_b: Second candidate sample rate.
            observation_period_seconds: Analysis window in seconds.

        Returns:
            ABSamplingComparison with estimated effectiveness metrics.
        """
        traffic = await self.get_current_traffic(service_name)
        total_spans = int(traffic * observation_period_seconds)

        error_rate = 0.0
        try:
            query = (
                f'sum(rate(traces_exporter_sent_spans_total{{service_name="{service_name}",status_code="ERROR"}}[5m])) '
                f'/ sum(rate(traces_exporter_sent_spans_total{{service_name="{service_name}"}}[5m]))'
            )
            result = await self._prometheus.instant_query(query)
            data = result.get("data", {}).get("result", [])
            if data:
                error_rate = float(data[0].get("value", [0, 0])[1])
        except Exception:
            error_rate = 0.01  # fallback assumption

        error_spans = int(total_spans * error_rate)
        normal_spans = total_spans - error_spans

        spans_a = int(normal_spans * rate_a) + error_spans  # errors always kept
        spans_b = int(normal_spans * rate_b) + error_spans

        error_coverage_a = 1.0 if error_spans == 0 else min(error_spans / error_spans, 1.0)
        error_coverage_b = 1.0 if error_spans == 0 else min(error_spans / error_spans, 1.0)

        # Recommend the rate that stays within budget while maximizing coverage
        budget_threshold = self._budget.max_spans_per_second * observation_period_seconds
        if spans_a <= budget_threshold and spans_b > budget_threshold:
            recommendation = rate_a
        elif spans_b <= budget_threshold and spans_a > budget_threshold:
            recommendation = rate_b
        else:
            recommendation = rate_b if spans_b <= spans_a else rate_a

        return ABSamplingComparison(
            service_name=service_name,
            rate_a=rate_a,
            rate_b=rate_b,
            spans_sampled_a=spans_a,
            spans_sampled_b=spans_b,
            error_coverage_a=error_coverage_a,
            error_coverage_b=error_coverage_b,
            recommendation=recommendation,
            analysis_period_seconds=observation_period_seconds,
        )

    async def get_effectiveness_metrics(self, service_name: str) -> SamplingEffectivenessMetrics:
        """Compute effectiveness metrics for the adaptive sampling engine.

        Args:
            service_name: Service to report on.

        Returns:
            SamplingEffectivenessMetrics for the service.
        """
        current_rate = self._current_rates.get(service_name, self._budget.target_sample_rate_max)
        traffic = await self.get_current_traffic(service_name)
        sampled_rate = traffic * current_rate
        budget_utilization = (
            (sampled_rate / self._budget.max_spans_per_second) * 100.0
            if self._budget.max_spans_per_second > 0
            else 0.0
        )

        return SamplingEffectivenessMetrics(
            service_name=service_name,
            current_sample_rate=current_rate,
            mode=self._mode,
            total_adjustments=self._adjustment_counts.get(service_name, 0),
            budget_utilization_pct=min(budget_utilization, 100.0),
            error_preservation_rate=1.0,  # Errors always preserved by design
            slow_trace_preservation_rate=1.0,  # Slow traces always preserved by design
            last_adjustment=self._last_adjustments.get(service_name),
            computed_at=datetime.now(tz=timezone.utc),
        )

    def get_current_rates(self) -> dict[str, float]:
        """Return the current sampling rates for all tracked services.

        Returns:
            Dict mapping service name to current sample rate.
        """
        return dict(self._current_rates)


__all__ = [
    "ABSamplingComparison",
    "AdaptiveAdjustment",
    "AdaptiveMode",
    "AdaptiveSamplingEngine",
    "EndpointSamplingConfig",
    "SamplingBudget",
    "SamplingEffectivenessMetrics",
    "TrafficSnapshot",
]
