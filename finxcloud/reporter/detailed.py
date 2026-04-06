"""Detailed report generator for FinXCloud AWS cost optimization."""

import logging
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class DetailedReporter:
    """Generates a comprehensive detailed report from scanned resources and cost data."""

    def __init__(self, resources: list[dict], cost_data: dict) -> None:
        self.resources = resources
        self.cost_data = cost_data

    def generate(self) -> dict:
        """Produce a detailed report dict with resource inventory and cost breakdown."""
        log.info("Generating detailed report for %d resources", len(self.resources))

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "resource_inventory": self._build_resource_inventory(),
            "cost_breakdown": self._build_cost_breakdown(),
            "resource_counts": self._build_resource_counts(),
        }

    # ------------------------------------------------------------------
    # Resource inventory
    # ------------------------------------------------------------------

    def _build_resource_inventory(self) -> dict:
        """Group resources by resource_type with counts and details."""
        grouped: dict[str, list[dict]] = defaultdict(list)
        for resource in self.resources:
            rtype = resource.get("resource_type", "unknown")
            grouped[rtype].append(resource)

        inventory: dict[str, dict] = {}
        for rtype, items in sorted(grouped.items()):
            inventory[rtype] = {
                "count": len(items),
                "details": items,
            }
        return inventory

    # ------------------------------------------------------------------
    # Cost breakdown
    # ------------------------------------------------------------------

    def _build_cost_breakdown(self) -> dict:
        """Extract and structure cost breakdown from cost_data."""
        by_service = self.cost_data.get("by_service", [])
        by_region = self.cost_data.get("by_region", [])
        by_account = self.cost_data.get("by_account", [])
        daily_trend = self.cost_data.get("daily_trend", [])

        # Sort each breakdown descending by amount for easier consumption.
        by_service_sorted = sorted(
            by_service, key=lambda e: e.get("amount", 0.0), reverse=True
        )
        by_region_sorted = sorted(
            by_region, key=lambda e: e.get("amount", 0.0), reverse=True
        )
        by_account_sorted = sorted(
            by_account, key=lambda e: e.get("amount", 0.0), reverse=True
        )

        total_cost_30d = self._compute_total_cost(by_service)

        log.info("Total 30-day cost: $%.2f", total_cost_30d)

        return {
            "by_service": by_service_sorted,
            "by_region": by_region_sorted,
            "by_account": by_account_sorted,
            "daily_trend": daily_trend,
            "total_cost_30d": total_cost_30d,
        }

    @staticmethod
    def _compute_total_cost(by_service: list[dict]) -> float:
        """Sum total cost across all services."""
        return round(sum(entry.get("amount", 0.0) for entry in by_service), 2)

    # ------------------------------------------------------------------
    # Resource counts
    # ------------------------------------------------------------------

    def _build_resource_counts(self) -> dict:
        """Return summary counts per resource type."""
        counts: dict[str, int] = defaultdict(int)
        for resource in self.resources:
            counts[resource.get("resource_type", "unknown")] += 1
        return dict(sorted(counts.items()))
