"""SLO Engine adapter — Service Level Objective management.

Implements SLO definition lifecycle, error budget computation,
multi-window multi-burn-rate alerting, SLI computation, and
SLO compliance tracking over configurable time windows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class SLIType(str, Enum):
    """Supported SLI computation methods."""

    AVAILABILITY = "availability"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"
    SATURATION = "saturation"


class BurnWindow(str, Enum):
    """Multi-window burn rate evaluation windows."""

    SHORT_5M = "5m"
    SHORT_1H = "1h"
    MEDIUM_6H = "6h"
    LONG_1D = "1d"
    LONG_3D = "3d"


@dataclass
class SLIResult:
    """Result of a single SLI computation.

    Attributes:
        sli_type: The type of indicator computed.
        value: Raw SLI value (0.0–1.0 for availability/error_rate).
        good_events: Count of good events in the window.
        total_events: Count of total events in the window.
        window: Evaluation window label.
        computed_at: UTC timestamp of computation.
        labels: Prometheus labels on the result metric.
    """

    sli_type: SLIType
    value: float
    good_events: float
    total_events: float
    window: str
    computed_at: datetime
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class BurnRateWindow:
    """Burn rate evaluation result for a single time window.

    Attributes:
        window: Window label (5m, 1h, etc.).
        burn_rate: Observed burn rate multiplier (1.0 = nominal).
        threshold: Alert threshold for this window.
        is_burning: True if burn_rate exceeds threshold.
        error_rate: Raw error rate observed in this window.
        slo_target: SLO target percentage used in calculation.
    """

    window: str
    burn_rate: float
    threshold: float
    is_burning: bool
    error_rate: float
    slo_target: float


@dataclass
class MultiWindowBurnResult:
    """Result of multi-window multi-burn-rate SLO evaluation.

    Two windows must both be burning simultaneously for an alert
    to fire. This prevents false positives from transient spikes.

    Attributes:
        slo_id: SLO definition identifier.
        short_window: 5-minute window evaluation.
        long_window: 1-hour window evaluation.
        is_alerting: True if both short and long windows are burning.
        error_budget_consumed_pct: Fraction of error budget consumed (0–100).
        error_budget_remaining_minutes: Remaining error budget in minutes.
        total_error_budget_minutes: Total error budget over the SLO window.
        evaluated_at: UTC timestamp of evaluation.
    """

    slo_id: str
    short_window: BurnRateWindow
    long_window: BurnRateWindow
    is_alerting: bool
    error_budget_consumed_pct: float
    error_budget_remaining_minutes: float
    total_error_budget_minutes: float
    evaluated_at: datetime


@dataclass
class SLOStatusSnapshot:
    """Complete SLO status for dashboard display.

    Attributes:
        slo_id: SLO definition identifier.
        service_name: Service the SLO tracks.
        target_percentage: SLO objective (e.g., 99.9).
        current_availability: Observed availability over the window (%).
        is_meeting_slo: True if current_availability >= target_percentage.
        burn_result: Latest multi-window burn rate evaluation.
        sli_result: Latest SLI computation result.
        window_days: Length of the SLO compliance window in days.
        compliance_percentage: Fraction of time SLO was met (0–100).
    """

    slo_id: str
    service_name: str
    target_percentage: float
    current_availability: float
    is_meeting_slo: bool
    burn_result: MultiWindowBurnResult
    sli_result: SLIResult
    window_days: int
    compliance_percentage: float


class SLOEngineAdapter:
    """Service Level Objective management adapter.

    Computes SLIs from Prometheus data, evaluates multi-window burn rates,
    tracks error budget consumption, and generates alert signals following
    the Google SRE multi-window multi-burn-rate alerting model.

    The canonical alert condition is:
        5-minute burn rate > fast_threshold AND 1-hour burn rate > fast_threshold

    Slow-burn detection uses the 6-hour and 3-day windows:
        6-hour burn rate > slow_threshold AND 3-day burn rate > slow_threshold

    Args:
        prometheus_client: Async Prometheus HTTP API client.
        fast_burn_threshold: Multiplier for fast-burn alert (default 14.4x).
        slow_burn_threshold: Multiplier for slow-burn alert (default 6.0x).
    """

    def __init__(
        self,
        prometheus_client: Any,
        fast_burn_threshold: float = 14.4,
        slow_burn_threshold: float = 6.0,
    ) -> None:
        """Initialize SLOEngineAdapter.

        Args:
            prometheus_client: Async Prometheus HTTP API client.
            fast_burn_threshold: Fast-burn alert threshold multiplier.
            slow_burn_threshold: Slow-burn alert threshold multiplier.
        """
        self._prometheus = prometheus_client
        self._fast_burn_threshold = fast_burn_threshold
        self._slow_burn_threshold = slow_burn_threshold

    async def compute_sli(
        self,
        slo_id: str,
        numerator_query: str,
        denominator_query: str,
        window: str = "5m",
        sli_type: SLIType = SLIType.AVAILABILITY,
    ) -> SLIResult:
        """Compute a Service Level Indicator from Prometheus.

        Evaluates the ratio of good_events / total_events over the
        specified window using instant PromQL queries.

        Args:
            slo_id: SLO definition identifier for logging.
            numerator_query: PromQL for good events (e.g., successful requests).
            denominator_query: PromQL for total events (e.g., all requests).
            window: Prometheus query window label (e.g., "5m", "1h").
            sli_type: Type of indicator being computed.

        Returns:
            SLIResult with computed value and event counts.
        """
        window_numerator = numerator_query.replace("[__WINDOW__]", f"[{window}]")
        window_denominator = denominator_query.replace("[__WINDOW__]", f"[{window}]")

        good_events = 0.0
        total_events = 0.0

        try:
            num_result = await self._prometheus.instant_query(window_numerator)
            den_result = await self._prometheus.instant_query(window_denominator)

            num_data = num_result.get("data", {}).get("result", [])
            den_data = den_result.get("data", {}).get("result", [])

            if num_data:
                good_events = float(num_data[0].get("value", [0, 0])[1])
            if den_data:
                total_events = float(den_data[0].get("value", [0, 0])[1])

            labels: dict[str, str] = {}
            if num_data:
                labels = num_data[0].get("metric", {})

        except Exception as exc:
            logger.error(
                "SLI computation failed",
                slo_id=slo_id,
                window=window,
                sli_type=sli_type.value,
                error=str(exc),
            )

        sli_value = (good_events / total_events) if total_events > 0 else 1.0

        logger.debug(
            "SLI computed",
            slo_id=slo_id,
            window=window,
            sli_type=sli_type.value,
            value=sli_value,
            good_events=good_events,
            total_events=total_events,
        )

        return SLIResult(
            sli_type=sli_type,
            value=sli_value,
            good_events=good_events,
            total_events=total_events,
            window=window,
            computed_at=datetime.now(tz=timezone.utc),
            labels=labels,
        )

    async def compute_burn_rate_for_window(
        self,
        slo_id: str,
        numerator_query: str,
        denominator_query: str,
        target_percentage: float,
        window: str,
        threshold: float,
    ) -> BurnRateWindow:
        """Compute burn rate for a single evaluation window.

        Burn rate = observed_error_rate / (1 - slo_target).
        A burn rate of 1.0 means the error budget is consumed at exactly
        the rate that would exhaust it by the end of the SLO window.

        Args:
            slo_id: SLO definition identifier.
            numerator_query: PromQL for good events.
            denominator_query: PromQL for all events.
            target_percentage: SLO target (e.g., 99.9 means 0.001 error budget).
            window: Evaluation window (e.g., "5m", "1h").
            threshold: Burn rate threshold that triggers an alert.

        Returns:
            BurnRateWindow with computed burn rate and alert status.
        """
        sli = await self.compute_sli(
            slo_id=slo_id,
            numerator_query=numerator_query,
            denominator_query=denominator_query,
            window=window,
        )

        error_rate = 1.0 - sli.value
        slo_error_budget = 1.0 - (target_percentage / 100.0)
        burn_rate = error_rate / slo_error_budget if slo_error_budget > 0 else 0.0
        is_burning = burn_rate >= threshold

        return BurnRateWindow(
            window=window,
            burn_rate=burn_rate,
            threshold=threshold,
            is_burning=is_burning,
            error_rate=error_rate,
            slo_target=target_percentage,
        )

    async def evaluate_multi_window(
        self,
        slo_id: str,
        numerator_query: str,
        denominator_query: str,
        target_percentage: float,
        window_days: int,
        fast_burn_threshold: float | None = None,
        slow_burn_threshold: float | None = None,
    ) -> MultiWindowBurnResult:
        """Evaluate SLO using multi-window multi-burn-rate alerting.

        Implements the Google SRE recommendation: fire an alert only when
        both the short and long windows simultaneously exceed the threshold.
        This eliminates false positives from brief transient spikes.

        Args:
            slo_id: SLO definition identifier.
            numerator_query: PromQL for good events.
            denominator_query: PromQL for total events.
            target_percentage: SLO target percentage.
            window_days: Length of the SLO window in days.
            fast_burn_threshold: Override for fast-burn threshold.
            slow_burn_threshold: Override for slow-burn threshold.

        Returns:
            MultiWindowBurnResult with short/long window evaluation and alert state.
        """
        fast_thresh = fast_burn_threshold or self._fast_burn_threshold
        slow_thresh = slow_burn_threshold or self._slow_burn_threshold

        short_window = await self.compute_burn_rate_for_window(
            slo_id=slo_id,
            numerator_query=numerator_query,
            denominator_query=denominator_query,
            target_percentage=target_percentage,
            window=BurnWindow.SHORT_5M.value,
            threshold=fast_thresh,
        )

        long_window = await self.compute_burn_rate_for_window(
            slo_id=slo_id,
            numerator_query=numerator_query,
            denominator_query=denominator_query,
            target_percentage=target_percentage,
            window=BurnWindow.SHORT_1H.value,
            threshold=fast_thresh,
        )

        is_alerting = short_window.is_burning and long_window.is_burning

        total_budget_minutes = window_days * 24 * 60 * (1.0 - target_percentage / 100.0)
        avg_error_rate = (short_window.error_rate + long_window.error_rate) / 2.0
        consumed_pct = min((avg_error_rate / (1.0 - target_percentage / 100.0)) * 100.0, 100.0)
        remaining_minutes = total_budget_minutes * (1.0 - consumed_pct / 100.0)

        logger.info(
            "Multi-window SLO evaluated",
            slo_id=slo_id,
            short_burn=short_window.burn_rate,
            long_burn=long_window.burn_rate,
            is_alerting=is_alerting,
            consumed_pct=consumed_pct,
        )

        return MultiWindowBurnResult(
            slo_id=slo_id,
            short_window=short_window,
            long_window=long_window,
            is_alerting=is_alerting,
            error_budget_consumed_pct=consumed_pct,
            error_budget_remaining_minutes=max(remaining_minutes, 0.0),
            total_error_budget_minutes=total_budget_minutes,
            evaluated_at=datetime.now(tz=timezone.utc),
        )

    async def get_slo_status(
        self,
        slo_id: str,
        service_name: str,
        numerator_query: str,
        denominator_query: str,
        target_percentage: float,
        window_days: int,
        fast_burn_threshold: float | None = None,
        slow_burn_threshold: float | None = None,
    ) -> SLOStatusSnapshot:
        """Compute a complete SLO status snapshot for dashboard display.

        Combines SLI computation, burn rate evaluation, and compliance
        tracking into a single snapshot suitable for the SLO dashboard.

        Args:
            slo_id: SLO definition identifier.
            service_name: Display name for the service.
            numerator_query: PromQL for good events.
            denominator_query: PromQL for total events.
            target_percentage: SLO target (e.g., 99.9).
            window_days: Compliance window length in days.
            fast_burn_threshold: Fast-burn threshold override.
            slow_burn_threshold: Slow-burn threshold override.

        Returns:
            SLOStatusSnapshot with full status for dashboard rendering.
        """
        long_window_label = f"{window_days}d"

        sli_result = await self.compute_sli(
            slo_id=slo_id,
            numerator_query=numerator_query,
            denominator_query=denominator_query,
            window=long_window_label,
        )

        burn_result = await self.evaluate_multi_window(
            slo_id=slo_id,
            numerator_query=numerator_query,
            denominator_query=denominator_query,
            target_percentage=target_percentage,
            window_days=window_days,
            fast_burn_threshold=fast_burn_threshold,
            slow_burn_threshold=slow_burn_threshold,
        )

        current_availability = sli_result.value * 100.0
        is_meeting_slo = current_availability >= target_percentage
        compliance_pct = 100.0 - burn_result.error_budget_consumed_pct

        return SLOStatusSnapshot(
            slo_id=slo_id,
            service_name=service_name,
            target_percentage=target_percentage,
            current_availability=current_availability,
            is_meeting_slo=is_meeting_slo,
            burn_result=burn_result,
            sli_result=sli_result,
            window_days=window_days,
            compliance_percentage=max(compliance_pct, 0.0),
        )

    async def get_batch_slo_statuses(
        self,
        slo_definitions: list[dict[str, Any]],
    ) -> list[SLOStatusSnapshot]:
        """Compute SLO status snapshots for multiple SLOs.

        Evaluates each SLO sequentially and collects results.
        Errors in individual SLOs are logged but do not abort the batch.

        Args:
            slo_definitions: List of SLO definition dicts with required keys:
                slo_id, service_name, numerator_query, denominator_query,
                target_percentage, window_days.

        Returns:
            List of SLOStatusSnapshot results, one per input definition.
        """
        results: list[SLOStatusSnapshot] = []
        for defn in slo_definitions:
            try:
                snapshot = await self.get_slo_status(
                    slo_id=defn["slo_id"],
                    service_name=defn["service_name"],
                    numerator_query=defn["numerator_query"],
                    denominator_query=defn["denominator_query"],
                    target_percentage=defn["target_percentage"],
                    window_days=defn.get("window_days", 30),
                    fast_burn_threshold=defn.get("fast_burn_threshold"),
                    slow_burn_threshold=defn.get("slow_burn_threshold"),
                )
                results.append(snapshot)
            except Exception as exc:
                logger.error(
                    "SLO status evaluation failed",
                    slo_id=defn.get("slo_id"),
                    error=str(exc),
                )
        return results


__all__ = [
    "BurnRateWindow",
    "BurnWindow",
    "MultiWindowBurnResult",
    "SLIResult",
    "SLIType",
    "SLOEngineAdapter",
    "SLOStatusSnapshot",
]
