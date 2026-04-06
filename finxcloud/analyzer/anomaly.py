"""Cost anomaly detection for FinXCloud.

Compares daily spend to a rolling 7-day average and flags spikes
that exceed a configurable threshold (default 30%).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from finxcloud.analyzer.cost_explorer import CostExplorerAnalyzer

log = logging.getLogger(__name__)

_DEFAULT_SPIKE_THRESHOLD = 0.30  # 30% above rolling average


class AnomalyDetector:
    """Detect cost anomalies by comparing daily spend to rolling averages."""

    def __init__(
        self,
        cost_explorer: CostExplorerAnalyzer,
        spike_threshold: float = _DEFAULT_SPIKE_THRESHOLD,
    ) -> None:
        self.ce = cost_explorer
        self.spike_threshold = spike_threshold

    def detect(self, days: int = 30) -> dict:
        """Run anomaly detection over the specified look-back window.

        Returns:
            Dict with keys: anomalies (list), daily_costs (list),
            rolling_averages (list), threshold_pct.
        """
        daily_costs = self.ce.get_daily_costs(days)
        if len(daily_costs) < 8:
            return {
                "anomalies": [],
                "daily_costs": daily_costs,
                "rolling_averages": [],
                "threshold_pct": round(self.spike_threshold * 100, 1),
            }

        anomalies: list[dict] = []
        rolling_averages: list[dict] = []

        for i in range(7, len(daily_costs)):
            window = daily_costs[i - 7 : i]
            avg = sum(d["amount"] for d in window) / 7.0
            current = daily_costs[i]
            current_amount = current["amount"]

            rolling_averages.append({
                "date": current["date"],
                "rolling_avg": round(avg, 4),
            })

            if avg > 0 and current_amount > avg * (1 + self.spike_threshold):
                pct_above = ((current_amount - avg) / avg) * 100
                anomalies.append({
                    "date": current["date"],
                    "amount": round(current_amount, 2),
                    "rolling_avg": round(avg, 2),
                    "pct_above_avg": round(pct_above, 1),
                    "severity": "high" if pct_above > 100 else "medium" if pct_above > 50 else "low",
                    "detected_at": datetime.now(tz=timezone.utc).isoformat(),
                })

        log.info(
            "Anomaly detection: %d anomalies found in %d days of data",
            len(anomalies), len(daily_costs),
        )

        return {
            "anomalies": anomalies,
            "daily_costs": daily_costs,
            "rolling_averages": rolling_averages,
            "threshold_pct": round(self.spike_threshold * 100, 1),
        }
