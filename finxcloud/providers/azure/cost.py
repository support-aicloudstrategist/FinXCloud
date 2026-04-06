"""Azure cost analysis for FinXCloud."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from finxcloud.providers.base import CloudCostAnalyzer

log = logging.getLogger(__name__)


class AzureCostAnalyzer(CloudCostAnalyzer):
    """Cost analysis using Azure Cost Management API."""

    def __init__(self, credential, subscription_id: str):
        self._credential = credential
        self._subscription_id = subscription_id

    def _query_costs(self, days: int, grouping: dict | None = None) -> list[dict]:
        """Execute a cost management query."""
        from azure.mgmt.costmanagement import CostManagementClient
        from azure.mgmt.costmanagement.models import (
            QueryDefinition,
            QueryTimePeriod,
            QueryDataset,
            QueryAggregation,
            QueryGrouping,
            ExportType,
            TimeframeType,
        )

        client = CostManagementClient(self._credential)
        scope = f"/subscriptions/{self._subscription_id}"

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        dataset_kwargs = {
            "aggregation": {
                "totalCost": QueryAggregation(name="Cost", function="Sum"),
            },
        }
        if grouping:
            dataset_kwargs["grouping"] = [
                QueryGrouping(type=grouping["type"], name=grouping["name"])
            ]

        query = QueryDefinition(
            type=ExportType.ACTUAL_COST,
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(from_property=start, to=end),
            dataset=QueryDataset(**dataset_kwargs),
        )

        result = client.query.usage(scope=scope, parameters=query)
        return result.rows if result.rows else []

    def get_cost_by_service(self, days: int = 30) -> list[dict]:
        try:
            rows = self._query_costs(days, grouping={"type": "Dimension", "name": "ServiceName"})
            return [
                {"service": row[1], "amount": float(row[0]), "unit": "USD", "currency": row[2] if len(row) > 2 else "USD"}
                for row in rows
            ]
        except Exception as e:
            log.warning("Azure cost by service unavailable: %s", e)
            return []

    def get_cost_by_region(self, days: int = 30) -> list[dict]:
        try:
            rows = self._query_costs(days, grouping={"type": "Dimension", "name": "ResourceLocation"})
            return [
                {"region": row[1], "amount": float(row[0]), "unit": "USD", "currency": row[2] if len(row) > 2 else "USD"}
                for row in rows
            ]
        except Exception as e:
            log.warning("Azure cost by region unavailable: %s", e)
            return []

    def get_daily_costs(self, days: int = 30) -> list[dict]:
        try:
            from azure.mgmt.costmanagement import CostManagementClient
            from azure.mgmt.costmanagement.models import (
                QueryDefinition,
                QueryTimePeriod,
                QueryDataset,
                QueryAggregation,
                ExportType,
                TimeframeType,
                GranularityType,
            )

            client = CostManagementClient(self._credential)
            scope = f"/subscriptions/{self._subscription_id}"

            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)

            query = QueryDefinition(
                type=ExportType.ACTUAL_COST,
                timeframe=TimeframeType.CUSTOM,
                time_period=QueryTimePeriod(from_property=start, to=end),
                dataset=QueryDataset(
                    granularity=GranularityType.DAILY,
                    aggregation={
                        "totalCost": QueryAggregation(name="Cost", function="Sum"),
                    },
                ),
            )

            result = client.query.usage(scope=scope, parameters=query)
            costs = []
            for row in (result.rows or []):
                date_val = str(row[1]) if len(row) > 1 else ""
                if len(date_val) == 8:
                    date_val = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:8]}"
                costs.append({"date": date_val, "amount": float(row[0])})
            return costs
        except Exception as e:
            log.warning("Azure daily costs unavailable: %s", e)
            return []

    def get_total_cost(self, days: int = 30) -> float:
        try:
            rows = self._query_costs(days)
            return sum(float(row[0]) for row in rows) if rows else 0.0
        except Exception as e:
            log.warning("Azure total cost unavailable: %s", e)
            return 0.0
