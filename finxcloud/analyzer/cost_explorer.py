"""Cost Explorer analysis module for FinXCloud AWS cost optimization."""

import logging
from datetime import date, timedelta

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


class CostExplorerAnalyzer:
    """Analyze AWS costs using the Cost Explorer API."""

    def __init__(self, session: boto3.Session) -> None:
        self.session = session
        self._client = session.client("ce")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cost_by_service(self, days: int = 30) -> list[dict]:
        """Return unblended cost grouped by AWS service.

        Args:
            days: Number of look-back days (default 30).

        Returns:
            List of dicts with keys: service, amount, unit, currency.
        """
        raw = self._query_cost_explorer(
            granularity="MONTHLY",
            group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            days=days,
        )
        return self._parse_grouped_results(raw, key_label="service")

    def get_cost_by_region(self, days: int = 30) -> list[dict]:
        """Return unblended cost grouped by AWS region.

        Args:
            days: Number of look-back days (default 30).

        Returns:
            List of dicts with keys: service (region name), amount, unit, currency.
        """
        raw = self._query_cost_explorer(
            granularity="MONTHLY",
            group_by=[{"Type": "DIMENSION", "Key": "REGION"}],
            days=days,
        )
        return self._parse_grouped_results(raw, key_label="service")

    def get_cost_by_account(self, days: int = 30) -> list[dict]:
        """Return unblended cost grouped by linked account (AWS Organizations).

        Args:
            days: Number of look-back days (default 30).

        Returns:
            List of dicts with keys: service (account id), amount, unit, currency.
        """
        raw = self._query_cost_explorer(
            granularity="MONTHLY",
            group_by=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}],
            days=days,
        )
        return self._parse_grouped_results(raw, key_label="service")

    def get_daily_costs(self, days: int = 30) -> list[dict]:
        """Return daily cost trend (no grouping).

        Args:
            days: Number of look-back days (default 30).

        Returns:
            List of dicts with keys: date, amount.
        """
        raw = self._query_cost_explorer(
            granularity="DAILY",
            group_by=None,
            days=days,
        )
        results: list[dict] = []
        for time_period in raw:
            start = time_period["TimePeriod"]["Start"]
            total = time_period.get("Total", {})
            unblended = total.get("UnblendedCost", {})
            amount = float(unblended.get("Amount", 0.0))
            results.append({"date": start, "amount": round(amount, 4)})
        return results

    def get_total_cost(self, days: int = 30) -> float:
        """Return total unblended cost over the given period.

        Args:
            days: Number of look-back days (default 30).

        Returns:
            Total cost as a float.
        """
        raw = self._query_cost_explorer(
            granularity="MONTHLY",
            group_by=None,
            days=days,
        )
        total = 0.0
        for time_period in raw:
            unblended = (
                time_period.get("Total", {}).get("UnblendedCost", {})
            )
            total += float(unblended.get("Amount", 0.0))
        return round(total, 4)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _query_cost_explorer(
        self,
        granularity: str,
        group_by: list[dict] | None,
        days: int,
    ) -> list[dict]:
        """Build time period and call Cost Explorer GetCostAndUsage.

        Args:
            granularity: DAILY or MONTHLY.
            group_by: Optional list of GROUP_BY definitions.
            days: Look-back window in days.

        Returns:
            The ``ResultsByTime`` list from the Cost Explorer response.

        Raises:
            RuntimeError: If the Cost Explorer API is not enabled or accessible.
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        params: dict = {
            "TimePeriod": {
                "Start": start_date.isoformat(),
                "End": end_date.isoformat(),
            },
            "Granularity": granularity,
            "Metrics": ["UnblendedCost"],
        }
        if group_by:
            params["GroupBy"] = group_by

        try:
            response = self._client.get_cost_and_usage(**params)
            return response.get("ResultsByTime", [])
        except ClientError as exc:
            error_code = exc.response["Error"].get("Code", "")
            if error_code in (
                "OptInRequired",
                "AccessDeniedException",
                "BillingAccessDenied",
            ):
                log.warning(
                    "Cost Explorer is not enabled or accessible: %s — %s",
                    error_code,
                    exc.response["Error"].get("Message", ""),
                )
                return []
            raise

    @staticmethod
    def _parse_grouped_results(
        results_by_time: list[dict],
        key_label: str = "service",
    ) -> list[dict]:
        """Aggregate grouped Cost Explorer results across time periods.

        Args:
            results_by_time: Raw ``ResultsByTime`` from the CE response.
            key_label: Label key used in the returned dicts.

        Returns:
            Aggregated list of dicts sorted by amount descending.
        """
        aggregated: dict[str, dict] = {}

        for time_period in results_by_time:
            for group in time_period.get("Groups", []):
                key_value = group["Keys"][0]
                metrics = group.get("Metrics", {}).get("UnblendedCost", {})
                amount = float(metrics.get("Amount", 0.0))
                unit = metrics.get("Unit", "USD")

                if key_value in aggregated:
                    aggregated[key_value]["amount"] += amount
                else:
                    aggregated[key_value] = {
                        key_label: key_value,
                        "amount": amount,
                        "unit": unit,
                        "currency": unit,
                    }

        results = list(aggregated.values())
        for entry in results:
            entry["amount"] = round(entry["amount"], 4)
        results.sort(key=lambda r: r["amount"], reverse=True)
        return results
