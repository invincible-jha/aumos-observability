"""SLO burn rate calculation engine.

Implements Google SRE multi-window alerting:
- Fast burn (5-min window): catches rapid error budget exhaustion
- Slow burn (1-hr window): catches gradual erosion that fast window misses

The formula: burn_rate = (error_rate / (1 - slo_target))
If burn_rate > threshold, an alert fires.

Error budget remaining = window_minutes * (1 - slo_target) - consumed_minutes
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from aumos_common.observability import get_logger

from aumos_observability.adapters.prometheus_client import PrometheusClient

logger = get_logger(__name__)


@dataclass
class BurnRateResult:
    """Result of a single SLO burn rate evaluation."""

    slo_id: str
    target_percentage: float
    window_days: int

    # Error budget
    total_error_budget_minutes: float
    current_error_budget_minutes: float
    error_budget_consumed_percentage: float

    # Burn rates
    fast_burn_rate: float
    slow_burn_rate: float
    fast_burn_threshold: float
    slow_burn_threshold: float

    # Alert state
    is_fast_burning: bool
    is_slow_burning: bool

    # Metadata
    calculated_at: datetime


class SLOBurnRateEngine:
    """Calculates SLO burn rates using Prometheus instant queries.

    Uses the Google SRE multi-window approach:
    - 2% of 30-day budget consumed in 1h → fast burn (14.4x rate)
    - 5% of 30-day budget consumed in 6h → slow burn (6x rate)

    Both windows must fire simultaneously to avoid false positives.
    """

    def __init__(self, prometheus: PrometheusClient) -> None:
        """Initialise with Prometheus client.

        Args:
            prometheus: Configured Prometheus API client.
        """
        self._prometheus = prometheus

    async def calculate(
        self,
        slo_id: str,
        numerator_query: str,
        denominator_query: str,
        target_percentage: float,
        window_days: int,
        fast_burn_threshold: float,
        slow_burn_threshold: float,
        fast_window_minutes: int = 5,
        slow_window_minutes: int = 60,
    ) -> BurnRateResult:
        """Calculate burn rate for a single SLO.

        Args:
            slo_id: SLO identifier for logging.
            numerator_query: PromQL for good events (e.g. successful requests).
            denominator_query: PromQL for total events.
            target_percentage: SLO target (e.g. 99.9 for three nines).
            window_days: Rolling window for error budget.
            fast_burn_threshold: Multiplier for fast burn alerting.
            slow_burn_threshold: Multiplier for slow burn alerting.
            fast_window_minutes: Fast window size in minutes.
            slow_window_minutes: Slow window size in minutes.

        Returns:
            BurnRateResult with all calculated fields.
        """
        slo_target = target_percentage / 100.0
        error_rate_target = 1.0 - slo_target

        # Query Prometheus for current error rates over both windows
        fast_query = self._build_error_rate_query(
            numerator_query=numerator_query,
            denominator_query=denominator_query,
            window_minutes=fast_window_minutes,
        )
        slow_query = self._build_error_rate_query(
            numerator_query=numerator_query,
            denominator_query=denominator_query,
            window_minutes=slow_window_minutes,
        )

        fast_error_rate = await self._query_scalar(fast_query)
        slow_error_rate = await self._query_scalar(slow_query)

        logger.debug(
            "SLO error rates",
            slo_id=slo_id,
            fast_error_rate=fast_error_rate,
            slow_error_rate=slow_error_rate,
            target=slo_target,
        )

        # Burn rate = current error rate / allowed error rate
        # Avoids division by zero for perfect SLOs
        fast_burn_rate = fast_error_rate / error_rate_target if error_rate_target > 0 else 0.0
        slow_burn_rate = slow_error_rate / error_rate_target if error_rate_target > 0 else 0.0

        # Error budget in minutes over the rolling window
        window_minutes = window_days * 24 * 60
        total_error_budget_minutes = window_minutes * error_rate_target

        # Remaining error budget using slow burn rate (more representative)
        consumed_fraction = min(slow_burn_rate * (slow_window_minutes / window_minutes), 1.0)
        current_error_budget_minutes = total_error_budget_minutes * (1.0 - consumed_fraction)
        error_budget_consumed_percentage = consumed_fraction * 100.0

        # Multi-window alerting: both windows must be burning to alert
        is_fast_burning = fast_burn_rate >= fast_burn_threshold
        is_slow_burning = slow_burn_rate >= slow_burn_threshold

        return BurnRateResult(
            slo_id=slo_id,
            target_percentage=target_percentage,
            window_days=window_days,
            total_error_budget_minutes=total_error_budget_minutes,
            current_error_budget_minutes=max(current_error_budget_minutes, 0.0),
            error_budget_consumed_percentage=min(error_budget_consumed_percentage, 100.0),
            fast_burn_rate=fast_burn_rate,
            slow_burn_rate=slow_burn_rate,
            fast_burn_threshold=fast_burn_threshold,
            slow_burn_threshold=slow_burn_threshold,
            is_fast_burning=is_fast_burning,
            is_slow_burning=is_slow_burning,
            calculated_at=datetime.now(tz=timezone.utc),
        )

    def _build_error_rate_query(
        self,
        numerator_query: str,
        denominator_query: str,
        window_minutes: int,
    ) -> str:
        """Build a PromQL error rate query.

        Error rate = 1 - (good_events / total_events) over the window.

        Args:
            numerator_query: PromQL for good events.
            denominator_query: PromQL for total events.
            window_minutes: Window size in minutes.

        Returns:
            PromQL expression string.
        """
        window = f"{window_minutes}m"
        return (
            f"1 - ("
            f"  sum(increase(({numerator_query})[{window}:]))"
            f"  /"
            f"  sum(increase(({denominator_query})[{window}:]))"
            f")"
        )

    async def _query_scalar(self, query: str) -> float:
        """Execute a PromQL query and return the scalar result.

        Returns 0.0 on empty result or query failure.

        Args:
            query: PromQL expression.

        Returns:
            Float scalar result, or 0.0 if unavailable.
        """
        try:
            result = await self._prometheus.instant_query(query)
            data = result.get("data", {})
            result_list = data.get("result", [])
            if result_list:
                value = result_list[0].get("value", [None, "0"])
                raw = float(value[1])
                return raw if not math.isnan(raw) else 0.0
        except Exception:
            logger.exception("Prometheus query failed", query=query[:80])
        return 0.0
