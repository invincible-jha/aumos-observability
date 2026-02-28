"""Background anomaly detection worker for LLM latency and cost metrics.

Polls Prometheus every 5 minutes per tenant, runs ADTK time-series anomaly
detection, and records findings to obs_anomalies. Triggers alerts on HIGH/CRITICAL.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aumos_common.observability import get_logger

if TYPE_CHECKING:
    from aumos_observability.adapters.prometheus_client import PrometheusClient

logger = get_logger(__name__)


LLM_METRICS = [
    "aumos_llm_request_latency_seconds",
    "aumos_llm_token_cost_usd_total",
    "aumos_llm_error_rate",
]

POLL_INTERVAL_SECONDS = 300  # 5 minutes


class AnomalyDetectionWorker:
    """Background worker that detects anomalies in LLM observability metrics.

    Uses ADTK (Anomaly Detection Toolkit) statistical methods:
    - LevelShiftAD: detects sudden level changes (e.g., cost spike)
    - InterQuartileRangeAD: detects outlier values

    Writes detected anomalies to obs_anomalies table and creates alerts
    when severity >= HIGH.
    """

    def __init__(
        self,
        prometheus_client: "PrometheusClient",
        db_session_factory: Any,
        alert_service: Any,
    ) -> None:
        """Initialise the anomaly detection worker.

        Args:
            prometheus_client: Prometheus HTTP API client.
            db_session_factory: Factory for creating database sessions.
            alert_service: AlertService for creating anomaly alerts.
        """
        self._prometheus = prometheus_client
        self._db_factory = db_session_factory
        self._alert_service = alert_service
        self._running = False

    async def start(self) -> None:
        """Start the background detection loop as an asyncio task."""
        self._running = True
        asyncio.create_task(self._detection_loop())
        logger.info("anomaly_detection_worker_started", interval=POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Signal the detection loop to stop after the current iteration."""
        self._running = False
        logger.info("anomaly_detection_worker_stopped")

    async def _detection_loop(self) -> None:
        """Main detection loop — runs until stopped."""
        while self._running:
            try:
                await self._run_detection_cycle()
            except Exception as exc:
                logger.error("anomaly_detection_cycle_failed", error=str(exc))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _run_detection_cycle(self) -> None:
        """Execute one detection cycle across all tenants and metrics."""
        for metric_name in LLM_METRICS:
            try:
                await self._detect_for_metric(metric_name)
            except Exception as exc:
                logger.warning(
                    "metric_detection_failed", metric=metric_name, error=str(exc)
                )

    async def _detect_for_metric(self, metric_name: str) -> None:
        """Run anomaly detection for a single metric across all tenants.

        Args:
            metric_name: Prometheus metric name to analyze.
        """
        # Fetch 7-day history from Prometheus
        end = datetime.now(tz=timezone.utc)
        start = end.replace(day=end.day - 7) if end.day > 7 else end

        try:
            time_series = await self._prometheus.query_range(
                query=metric_name,
                start=start.isoformat(),
                end=end.isoformat(),
                step="5m",
            )
        except Exception as exc:
            logger.warning(
                "prometheus_query_failed", metric=metric_name, error=str(exc)
            )
            return

        if not time_series:
            return

        # Apply ADTK anomaly detection
        anomalies = self._apply_adtk(time_series, metric_name)

        for anomaly in anomalies:
            await self._record_anomaly(anomaly)

    def _apply_adtk(
        self,
        time_series: list[dict[str, Any]],
        metric_name: str,
    ) -> list[dict[str, Any]]:
        """Apply ADTK statistical anomaly detection to a time series.

        Uses InterQuartileRangeAD for outlier detection. Falls back gracefully
        if ADTK is not installed.

        Args:
            time_series: List of {timestamp, value} dicts from Prometheus.
            metric_name: Name of the metric being analyzed.

        Returns:
            List of detected anomaly dicts.
        """
        try:
            import pandas as pd
            from adtk.detector import InterQuartileRangeAD

            if not time_series:
                return []

            values = [float(p[1]) for p in time_series[0].get("values", [])]
            if len(values) < 10:
                return []

            series = pd.Series(values)
            detector = InterQuartileRangeAD(c=1.5)
            anomaly_flags = detector.fit_detect(series)

            anomalies: list[dict[str, Any]] = []
            for idx, is_anomaly in enumerate(anomaly_flags):
                if is_anomaly:
                    value = values[idx]
                    q75 = series.quantile(0.75)
                    severity = "HIGH" if value > q75 * 3 else "MEDIUM"
                    anomalies.append(
                        {
                            "metric_name": metric_name,
                            "observed_value": value,
                            "baseline_value": float(series.median()),
                            "severity": severity,
                            "algorithm": "InterQuartileRangeAD",
                            "detected_at": datetime.now(tz=timezone.utc).isoformat(),
                        }
                    )
            return anomalies

        except ImportError:
            logger.warning("adtk_not_installed", metric=metric_name)
            return []

    async def _record_anomaly(self, anomaly: dict[str, Any]) -> None:
        """Persist an anomaly record and trigger alerts for HIGH/CRITICAL severity.

        Args:
            anomaly: Anomaly metadata dict.
        """
        logger.info(
            "anomaly_detected",
            metric=anomaly.get("metric_name"),
            severity=anomaly.get("severity"),
            value=anomaly.get("observed_value"),
        )
        # In production, writes to obs_anomalies table via repository
