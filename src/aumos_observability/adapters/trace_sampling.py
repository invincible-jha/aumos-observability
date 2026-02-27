"""Trace Sampling adapter — intelligent trace sampling strategies.

Implements head-based probabilistic sampling, tail-based error/latency
retention sampling, priority sampling (errors always kept), per-service
configuration, and sampling impact analysis.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class SamplingDecision(str, Enum):
    """Final sampling decision for a trace."""

    SAMPLED = "sampled"
    NOT_SAMPLED = "not_sampled"
    PRIORITY_SAMPLED = "priority_sampled"  # Always kept regardless of rate


class SamplingStrategy(str, Enum):
    """Sampling strategy applied to reach a decision."""

    HEAD_PROBABILISTIC = "head_probabilistic"
    TAIL_ERROR = "tail_error"
    TAIL_LATENCY = "tail_latency"
    PRIORITY_ERROR = "priority_error"
    PRIORITY_SLOW = "priority_slow"
    RATE_LIMITED = "rate_limited"


@dataclass
class ServiceSamplingConfig:
    """Per-service trace sampling configuration.

    Attributes:
        service_name: Prometheus/OTEL service name.
        head_sample_rate: Fraction of traces to sample at head (0.0–1.0).
        error_always_sample: Always keep traces with error status codes.
        latency_threshold_ms: Tail-sample traces slower than this (0 disables).
        max_traces_per_second: Hard rate limit per service (0 for unlimited).
        enabled: Whether sampling is active for this service.
    """

    service_name: str
    head_sample_rate: float = 0.1
    error_always_sample: bool = True
    latency_threshold_ms: float = 1000.0
    max_traces_per_second: float = 0.0
    enabled: bool = True


@dataclass
class TraceAttributes:
    """Attributes of a trace used to make sampling decisions.

    Attributes:
        trace_id: 128-bit trace identifier (hex string).
        service_name: Originating service name.
        operation_name: Span operation name.
        duration_ms: Observed trace duration in milliseconds.
        has_error: True if any span in the trace has an error status.
        http_status_code: HTTP status code if applicable (None otherwise).
        user_id: Optional user identifier for user-based sampling.
        tenant_id: Optional tenant identifier for tenant-based sampling.
        custom_attributes: Additional span attributes.
    """

    trace_id: str
    service_name: str
    operation_name: str
    duration_ms: float = 0.0
    has_error: bool = False
    http_status_code: int | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    custom_attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class SamplingResult:
    """Result of the sampling decision for a single trace.

    Attributes:
        trace_id: Trace identifier.
        decision: Final sampling decision.
        strategy: Strategy that produced this decision.
        sample_rate: Effective sample rate applied (0.0–1.0).
        reason: Human-readable reason for the decision.
        decided_at: UTC timestamp of decision.
    """

    trace_id: str
    decision: SamplingDecision
    strategy: SamplingStrategy
    sample_rate: float
    reason: str
    decided_at: datetime


@dataclass
class SamplingImpactReport:
    """Analysis of sampling effectiveness over a time period.

    Attributes:
        service_name: Service name analyzed.
        period_seconds: Duration of the analysis window.
        total_traces: Total traces considered in the period.
        sampled_traces: Traces that were kept.
        dropped_traces: Traces that were dropped.
        priority_sampled: Traces kept due to priority rules (errors/slow).
        effective_sample_rate: Actual observed sample rate.
        estimated_storage_reduction_pct: Estimated storage saving vs. 100% sampling.
        error_coverage_pct: Fraction of error traces that were kept.
        p99_latency_coverage_pct: Fraction of slow traces that were kept.
    """

    service_name: str
    period_seconds: float
    total_traces: int
    sampled_traces: int
    dropped_traces: int
    priority_sampled: int
    effective_sample_rate: float
    estimated_storage_reduction_pct: float
    error_coverage_pct: float
    p99_latency_coverage_pct: float


class TraceSamplingAdapter:
    """Intelligent trace sampling adapter.

    Provides head-based probabilistic sampling with tail-based override
    rules that ensure errors and slow traces are always retained regardless
    of head sampling rate. Supports per-service configuration.

    Priority sampling rules always override head-based rates:
    1. Errors (has_error=True or 5xx status codes) are always sampled.
    2. Slow traces exceeding latency_threshold_ms are always sampled.
    3. Head-based probabilistic sampling applies to all other traces.
    4. Rate limits (max_traces_per_second) cap throughput per service.

    Args:
        default_head_sample_rate: Default fraction of traces to sample (0.0–1.0).
        default_latency_threshold_ms: Default latency threshold for tail sampling.
        always_sample_errors: Global setting to always keep error traces.
    """

    def __init__(
        self,
        default_head_sample_rate: float = 0.1,
        default_latency_threshold_ms: float = 1000.0,
        always_sample_errors: bool = True,
    ) -> None:
        """Initialize TraceSamplingAdapter.

        Args:
            default_head_sample_rate: Default head sampling rate (0.0–1.0).
            default_latency_threshold_ms: Default tail sampling latency threshold ms.
            always_sample_errors: Global override to always keep error traces.
        """
        self._default_head_rate = default_head_sample_rate
        self._default_latency_threshold_ms = default_latency_threshold_ms
        self._always_sample_errors = always_sample_errors
        self._service_configs: dict[str, ServiceSamplingConfig] = {}
        # Rate limit state: service_name -> (token_count, last_refill_time)
        self._rate_limit_state: dict[str, tuple[float, float]] = {}

    def configure_service(self, config: ServiceSamplingConfig) -> None:
        """Set per-service sampling configuration.

        Args:
            config: ServiceSamplingConfig for the named service.
        """
        self._service_configs[config.service_name] = config
        logger.info(
            "Service sampling configured",
            service_name=config.service_name,
            head_sample_rate=config.head_sample_rate,
            latency_threshold_ms=config.latency_threshold_ms,
            error_always_sample=config.error_always_sample,
        )

    def _get_config(self, service_name: str) -> ServiceSamplingConfig:
        """Get sampling config for a service, falling back to defaults.

        Args:
            service_name: Service name.

        Returns:
            ServiceSamplingConfig (per-service or default).
        """
        if service_name in self._service_configs:
            return self._service_configs[service_name]
        return ServiceSamplingConfig(
            service_name=service_name,
            head_sample_rate=self._default_head_rate,
            error_always_sample=self._always_sample_errors,
            latency_threshold_ms=self._default_latency_threshold_ms,
        )

    def _is_priority_trace(
        self,
        trace: TraceAttributes,
        config: ServiceSamplingConfig,
    ) -> tuple[bool, SamplingStrategy, str]:
        """Check if a trace qualifies for priority sampling.

        Priority traces are always kept regardless of head sampling rate.

        Args:
            trace: Trace attributes.
            config: Service sampling configuration.

        Returns:
            Tuple of (is_priority, strategy, reason).
        """
        if (config.error_always_sample or self._always_sample_errors) and trace.has_error:
            return True, SamplingStrategy.PRIORITY_ERROR, "Trace contains errors — priority sampled"

        if (config.error_always_sample or self._always_sample_errors) and (
            trace.http_status_code is not None and trace.http_status_code >= 500
        ):
            return (
                True,
                SamplingStrategy.PRIORITY_ERROR,
                f"HTTP {trace.http_status_code} response — priority sampled",
            )

        if config.latency_threshold_ms > 0 and trace.duration_ms >= config.latency_threshold_ms:
            return (
                True,
                SamplingStrategy.PRIORITY_SLOW,
                f"Trace duration {trace.duration_ms:.1f}ms exceeds threshold {config.latency_threshold_ms:.1f}ms",
            )

        return False, SamplingStrategy.HEAD_PROBABILISTIC, ""

    def _head_sample(self, trace_id: str, sample_rate: float) -> bool:
        """Apply deterministic head-based probabilistic sampling.

        Uses the trace ID hash to ensure consistent sampling decisions
        across services — the same trace ID always produces the same outcome.

        Args:
            trace_id: Trace identifier (hex string).
            sample_rate: Fraction of traces to keep (0.0–1.0).

        Returns:
            True if this trace should be sampled.
        """
        if sample_rate >= 1.0:
            return True
        if sample_rate <= 0.0:
            return False
        hash_value = int(hashlib.md5(trace_id.encode(), usedforsecurity=False).hexdigest()[:8], 16)
        normalized = hash_value / 0xFFFFFFFF
        return normalized < sample_rate

    def _check_rate_limit(self, service_name: str, max_per_second: float) -> bool:
        """Token-bucket rate limiter for per-service trace throughput.

        Args:
            service_name: Service identifier.
            max_per_second: Maximum traces per second allowed.

        Returns:
            True if the trace is within the rate limit (should be considered for sampling).
        """
        if max_per_second <= 0:
            return True

        now = time.monotonic()
        tokens, last_refill = self._rate_limit_state.get(service_name, (max_per_second, now))
        elapsed = now - last_refill
        tokens = min(max_per_second, tokens + elapsed * max_per_second)

        if tokens >= 1.0:
            self._rate_limit_state[service_name] = (tokens - 1.0, now)
            return True

        self._rate_limit_state[service_name] = (tokens, now)
        return False

    def decide(self, trace: TraceAttributes) -> SamplingResult:
        """Make a sampling decision for a single trace.

        Applies priority rules first, then head-based probabilistic sampling,
        then rate limiting. Decisions are logged for impact analysis.

        Args:
            trace: Trace attributes describing the candidate trace.

        Returns:
            SamplingResult with the final decision and rationale.
        """
        config = self._get_config(trace.service_name)

        if not config.enabled:
            return SamplingResult(
                trace_id=trace.trace_id,
                decision=SamplingDecision.NOT_SAMPLED,
                strategy=SamplingStrategy.HEAD_PROBABILISTIC,
                sample_rate=0.0,
                reason=f"Sampling disabled for service {trace.service_name}",
                decided_at=datetime.now(tz=timezone.utc),
            )

        is_priority, priority_strategy, priority_reason = self._is_priority_trace(trace, config)
        if is_priority:
            logger.debug(
                "Priority sampling applied",
                trace_id=trace.trace_id,
                service=trace.service_name,
                strategy=priority_strategy.value,
                reason=priority_reason,
            )
            return SamplingResult(
                trace_id=trace.trace_id,
                decision=SamplingDecision.PRIORITY_SAMPLED,
                strategy=priority_strategy,
                sample_rate=1.0,
                reason=priority_reason,
                decided_at=datetime.now(tz=timezone.utc),
            )

        if config.max_traces_per_second > 0 and not self._check_rate_limit(
            trace.service_name, config.max_traces_per_second
        ):
            return SamplingResult(
                trace_id=trace.trace_id,
                decision=SamplingDecision.NOT_SAMPLED,
                strategy=SamplingStrategy.RATE_LIMITED,
                sample_rate=0.0,
                reason=f"Rate limit {config.max_traces_per_second:.1f} tps exceeded",
                decided_at=datetime.now(tz=timezone.utc),
            )

        sampled = self._head_sample(trace.trace_id, config.head_sample_rate)
        decision = SamplingDecision.SAMPLED if sampled else SamplingDecision.NOT_SAMPLED
        reason = (
            f"Head sampling at rate {config.head_sample_rate:.3f}: {'kept' if sampled else 'dropped'}"
        )

        return SamplingResult(
            trace_id=trace.trace_id,
            decision=decision,
            strategy=SamplingStrategy.HEAD_PROBABILISTIC,
            sample_rate=config.head_sample_rate,
            reason=reason,
            decided_at=datetime.now(tz=timezone.utc),
        )

    def decide_batch(self, traces: list[TraceAttributes]) -> list[SamplingResult]:
        """Make sampling decisions for a batch of traces.

        Args:
            traces: List of TraceAttributes to evaluate.

        Returns:
            Corresponding list of SamplingResult decisions.
        """
        return [self.decide(trace) for trace in traces]

    def analyze_impact(
        self,
        results: list[SamplingResult],
        period_seconds: float,
        service_name: str,
    ) -> SamplingImpactReport:
        """Analyze the impact of sampling decisions over a period.

        Args:
            results: List of SamplingResult from decide() or decide_batch().
            period_seconds: Duration of the analysis window in seconds.
            service_name: Service name for the report.

        Returns:
            SamplingImpactReport with effectiveness metrics.
        """
        total = len(results)
        sampled = sum(
            1 for r in results
            if r.decision in (SamplingDecision.SAMPLED, SamplingDecision.PRIORITY_SAMPLED)
        )
        priority_sampled = sum(
            1 for r in results if r.decision == SamplingDecision.PRIORITY_SAMPLED
        )
        dropped = total - sampled

        effective_rate = sampled / total if total > 0 else 0.0
        storage_reduction = (1.0 - effective_rate) * 100.0

        error_traces = [r for r in results if r.strategy == SamplingStrategy.PRIORITY_ERROR]
        error_coverage = 1.0 if not error_traces else sum(
            1 for r in error_traces if r.decision != SamplingDecision.NOT_SAMPLED
        ) / len(error_traces)

        slow_traces = [r for r in results if r.strategy == SamplingStrategy.PRIORITY_SLOW]
        slow_coverage = 1.0 if not slow_traces else sum(
            1 for r in slow_traces if r.decision != SamplingDecision.NOT_SAMPLED
        ) / len(slow_traces)

        return SamplingImpactReport(
            service_name=service_name,
            period_seconds=period_seconds,
            total_traces=total,
            sampled_traces=sampled,
            dropped_traces=dropped,
            priority_sampled=priority_sampled,
            effective_sample_rate=effective_rate,
            estimated_storage_reduction_pct=storage_reduction,
            error_coverage_pct=error_coverage * 100.0,
            p99_latency_coverage_pct=slow_coverage * 100.0,
        )

    def get_service_configs(self) -> dict[str, ServiceSamplingConfig]:
        """Return all configured service sampling configurations.

        Returns:
            Dict mapping service name to ServiceSamplingConfig.
        """
        return dict(self._service_configs)


__all__ = [
    "SamplingDecision",
    "SamplingImpactReport",
    "SamplingResult",
    "SamplingStrategy",
    "ServiceSamplingConfig",
    "TraceAttributes",
    "TraceSamplingAdapter",
]
