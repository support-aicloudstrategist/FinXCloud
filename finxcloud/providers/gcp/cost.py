"""GCP cost analysis for FinXCloud."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from finxcloud.providers.base import CloudCostAnalyzer

log = logging.getLogger(__name__)


class GCPCostAnalyzer(CloudCostAnalyzer):
    """Cost analysis using GCP Cloud Billing API via BigQuery export."""

    def __init__(self, credentials, project_id: str, billing_account_id: str = ""):
        self._credentials = credentials
        self._project_id = project_id
        self._billing_account_id = billing_account_id

    def _query_billing(self, days: int, group_by: str | None = None) -> list[dict]:
        """Query billing data via the Cloud Billing API."""
        from google.cloud import billing_v1

        client = billing_v1.CloudBillingClient(credentials=self._credentials)

        if not self._billing_account_id:
            accounts = list(client.list_billing_accounts())
            if accounts:
                self._billing_account_id = accounts[0].name.split("/")[-1]
            else:
                log.warning("No billing accounts found")
                return []

        # Use the Cloud Billing Budgets or export; for PoC return empty
        # Real implementation would query BigQuery billing export
        log.info(
            "GCP billing query: days=%d, group_by=%s, billing_account=%s",
            days, group_by, self._billing_account_id,
        )
        return []

    def get_cost_by_service(self, days: int = 30) -> list[dict]:
        try:
            from google.cloud import bigquery

            client = bigquery.Client(project=self._project_id, credentials=self._credentials)
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)

            query = f"""
                SELECT service.description AS service,
                       SUM(cost) AS amount,
                       currency
                FROM `{self._project_id}.billing_export.gcp_billing_export_v1_*`
                WHERE usage_start_time >= @start AND usage_start_time < @end
                GROUP BY service, currency
                ORDER BY amount DESC
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
                    bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
                ]
            )
            results = client.query(query, job_config=job_config)
            return [
                {"service": row.service, "amount": float(row.amount), "unit": "USD", "currency": row.currency}
                for row in results
            ]
        except Exception as e:
            log.warning("GCP cost by service unavailable: %s", e)
            return []

    def get_cost_by_region(self, days: int = 30) -> list[dict]:
        try:
            from google.cloud import bigquery

            client = bigquery.Client(project=self._project_id, credentials=self._credentials)
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)

            query = f"""
                SELECT location.region AS region,
                       SUM(cost) AS amount,
                       currency
                FROM `{self._project_id}.billing_export.gcp_billing_export_v1_*`
                WHERE usage_start_time >= @start AND usage_start_time < @end
                GROUP BY region, currency
                ORDER BY amount DESC
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
                    bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
                ]
            )
            results = client.query(query, job_config=job_config)
            return [
                {"region": row.region or "global", "amount": float(row.amount), "unit": "USD", "currency": row.currency}
                for row in results
            ]
        except Exception as e:
            log.warning("GCP cost by region unavailable: %s", e)
            return []

    def get_daily_costs(self, days: int = 30) -> list[dict]:
        try:
            from google.cloud import bigquery

            client = bigquery.Client(project=self._project_id, credentials=self._credentials)
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)

            query = f"""
                SELECT DATE(usage_start_time) AS date,
                       SUM(cost) AS amount
                FROM `{self._project_id}.billing_export.gcp_billing_export_v1_*`
                WHERE usage_start_time >= @start AND usage_start_time < @end
                GROUP BY date
                ORDER BY date
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
                    bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
                ]
            )
            results = client.query(query, job_config=job_config)
            return [
                {"date": str(row.date), "amount": float(row.amount)}
                for row in results
            ]
        except Exception as e:
            log.warning("GCP daily costs unavailable: %s", e)
            return []

    def get_total_cost(self, days: int = 30) -> float:
        try:
            from google.cloud import bigquery

            client = bigquery.Client(project=self._project_id, credentials=self._credentials)
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)

            query = f"""
                SELECT SUM(cost) AS total
                FROM `{self._project_id}.billing_export.gcp_billing_export_v1_*`
                WHERE usage_start_time >= @start AND usage_start_time < @end
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
                    bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
                ]
            )
            results = client.query(query, job_config=job_config)
            for row in results:
                return float(row.total) if row.total else 0.0
            return 0.0
        except Exception as e:
            log.warning("GCP total cost unavailable: %s", e)
            return 0.0
