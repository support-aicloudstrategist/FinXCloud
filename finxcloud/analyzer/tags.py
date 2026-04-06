"""Tag-based cost allocation analyzer for FinXCloud.

Groups AWS Cost Explorer data by user-defined allocation tags
(e.g. Team, Project, Environment) so costs can be attributed to
business units, projects, or environments.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


class TagCostAllocator:
    """Query AWS Cost Explorer grouped by cost-allocation tags."""

    def __init__(self, session: boto3.Session) -> None:
        self.session = session
        self._client = session.client("ce")

    def get_cost_by_tags(
        self,
        tag_keys: list[str],
        days: int = 30,
    ) -> dict:
        """Return cost breakdown grouped by each specified tag key.

        Args:
            tag_keys: List of AWS cost-allocation tag keys
                      (e.g. ``["Team", "Project", "Environment"]``).
            days: Look-back window in days (default 30).

        Returns:
            A dict with structure::

                {
                    "days": 30,
                    "by_tag": [
                        {
                            "tag_key": "Team",
                            "values": [
                                {"value": "Platform", "amount": 1234.56},
                                {"value": "Untagged", "amount": 567.89},
                            ],
                            "total": 1802.45,
                        },
                        ...
                    ]
                }
        """
        results: list[dict] = []
        for tag_key in tag_keys:
            tag_data = self._query_by_tag(tag_key, days)
            results.append(tag_data)

        return {"days": days, "by_tag": results}

    def get_cost_by_single_tag(self, tag_key: str, days: int = 30) -> dict:
        """Return cost breakdown for a single tag key."""
        return self._query_by_tag(tag_key, days)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _query_by_tag(self, tag_key: str, days: int) -> dict:
        """Query Cost Explorer grouped by a single tag key."""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        params: dict = {
            "TimePeriod": {
                "Start": start_date.isoformat(),
                "End": end_date.isoformat(),
            },
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "TAG", "Key": tag_key}],
        }

        try:
            response = self._client.get_cost_and_usage(**params)
            results_by_time = response.get("ResultsByTime", [])
        except ClientError as exc:
            error_code = exc.response["Error"].get("Code", "")
            if error_code in (
                "OptInRequired",
                "AccessDeniedException",
                "BillingAccessDenied",
            ):
                log.warning(
                    "Cost Explorer tag query not accessible for tag '%s': %s",
                    tag_key,
                    exc.response["Error"].get("Message", ""),
                )
                return {"tag_key": tag_key, "values": [], "total": 0.0}
            raise

        # Aggregate across time periods
        aggregated: dict[str, float] = {}
        for tp in results_by_time:
            for group in tp.get("Groups", []):
                raw_key = group["Keys"][0]
                # AWS returns "Tag$Key$Value" or just the value depending on
                # the group-by type.  TAG groups return the tag value directly,
                # or an empty string for untagged resources.
                value = raw_key
                # Strip the "TagKey$" prefix if present
                prefix = f"{tag_key}$"
                if value.startswith(prefix):
                    value = value[len(prefix):]
                if not value:
                    value = "Untagged"

                amount = float(
                    group.get("Metrics", {})
                    .get("UnblendedCost", {})
                    .get("Amount", 0.0)
                )
                aggregated[value] = aggregated.get(value, 0.0) + amount

        values = sorted(
            [
                {"value": v, "amount": round(a, 4)}
                for v, a in aggregated.items()
            ],
            key=lambda x: x["amount"],
            reverse=True,
        )

        total = round(sum(v["amount"] for v in values), 4)
        return {"tag_key": tag_key, "values": values, "total": total}
