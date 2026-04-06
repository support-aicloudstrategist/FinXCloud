"""Executive summary report generator for FinXCloud AWS cost optimization."""

import logging
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class SummaryReporter:
    """Generates an executive summary from a detailed report and recommendations."""

    def __init__(self, detailed_report: dict, recommendations: list[dict]) -> None:
        self.detailed_report = detailed_report
        self.recommendations = recommendations

    def generate(self) -> dict:
        """Produce an executive summary dict."""
        log.info(
            "Generating executive summary with %d recommendations",
            len(self.recommendations),
        )

        total_resources = sum(
            self.detailed_report.get("resource_counts", {}).values()
        )
        total_cost_30d = (
            self.detailed_report
            .get("cost_breakdown", {})
            .get("total_cost_30d", 0.0)
        )
        total_potential_savings = round(
            sum(r.get("estimated_monthly_savings", 0.0) for r in self.recommendations), 2
        )
        savings_percentage = (
            round((total_potential_savings / total_cost_30d) * 100, 1)
            if total_cost_30d > 0
            else 0.0
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overview": {
                "total_resources": total_resources,
                "total_cost_30d": total_cost_30d,
                "total_potential_savings": total_potential_savings,
                "savings_percentage": savings_percentage,
            },
            "top_cost_services": self._top_cost_services(),
            "top_recommendations": self._top_recommendations(),
            "savings_by_category": self._savings_by_category(),
            "quick_wins_count": self._quick_wins_count(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _top_cost_services(self, limit: int = 5) -> list[dict]:
        """Return the top *limit* services ranked by cost."""
        by_service = (
            self.detailed_report
            .get("cost_breakdown", {})
            .get("by_service", [])
        )
        sorted_services = sorted(
            by_service, key=lambda s: s.get("amount", 0.0), reverse=True
        )
        return sorted_services[:limit]

    def _top_recommendations(self, limit: int = 10) -> list[dict]:
        """Return the top *limit* recommendations ranked by estimated savings."""
        sorted_recs = sorted(
            self.recommendations,
            key=lambda r: r.get("estimated_monthly_savings", 0.0),
            reverse=True,
        )
        return sorted_recs[:limit]

    def _savings_by_category(self) -> list[dict]:
        """Aggregate estimated savings grouped by recommendation category."""
        buckets: dict[str, float] = defaultdict(float)
        for rec in self.recommendations:
            category = rec.get("category", "uncategorized")
            buckets[category] += rec.get("estimated_monthly_savings", 0.0)

        return sorted(
            [
                {"category": cat, "estimated_monthly_savings": round(amt, 2)}
                for cat, amt in buckets.items()
            ],
            key=lambda e: e["estimated_monthly_savings"],
            reverse=True,
        )

    def _quick_wins_count(self) -> int:
        """Count recommendations whose effort_level is 'low'."""
        return sum(
            1
            for r in self.recommendations
            if r.get("effort_level", "").lower() == "low"
        )
