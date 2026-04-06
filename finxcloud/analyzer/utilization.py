"""Resource utilization analysis module for FinXCloud AWS cost optimization."""

import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


class UtilizationAnalyzer:
    """Analyze AWS resource utilization via CloudWatch metrics."""

    def __init__(self, session: boto3.Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_ec2_utilization(
        self,
        instance_id: str,
        region: str,
        days: int = 14,
    ) -> dict:
        """Return CPU and network utilization for an EC2 instance.

        Args:
            instance_id: The EC2 instance ID (e.g. ``i-0abc123``).
            region: AWS region the instance runs in.
            days: Look-back window in days (default 14).

        Returns:
            Dict with keys: instance_id, avg_cpu, max_cpu, avg_network_in.
            Values are ``None`` when the metric is unavailable.
        """
        dimensions = [{"Name": "InstanceId", "Value": instance_id}]

        avg_cpu = self._get_metric_stats(
            region=region,
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            dimensions=dimensions,
            stat="Average",
            period=3600,
            days=days,
        )

        max_cpu = self._get_metric_stats(
            region=region,
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            dimensions=dimensions,
            stat="Maximum",
            period=3600,
            days=days,
        )

        avg_network_in = self._get_metric_stats(
            region=region,
            namespace="AWS/EC2",
            metric_name="NetworkIn",
            dimensions=dimensions,
            stat="Average",
            period=3600,
            days=days,
        )

        return {
            "instance_id": instance_id,
            "avg_cpu": _safe_avg(avg_cpu),
            "max_cpu": _safe_max(max_cpu),
            "avg_network_in": _safe_avg(avg_network_in),
        }

    def get_rds_utilization(
        self,
        db_instance_id: str,
        region: str,
        days: int = 14,
    ) -> dict:
        """Return CPU and connection utilization for an RDS instance.

        Args:
            db_instance_id: The RDS DB instance identifier.
            region: AWS region the instance runs in.
            days: Look-back window in days (default 14).

        Returns:
            Dict with keys: db_instance_id, avg_cpu, max_cpu,
            avg_connections, max_connections.
        """
        dimensions = [{"Name": "DBInstanceIdentifier", "Value": db_instance_id}]

        avg_cpu = self._get_metric_stats(
            region=region,
            namespace="AWS/RDS",
            metric_name="CPUUtilization",
            dimensions=dimensions,
            stat="Average",
            period=3600,
            days=days,
        )

        max_cpu = self._get_metric_stats(
            region=region,
            namespace="AWS/RDS",
            metric_name="CPUUtilization",
            dimensions=dimensions,
            stat="Maximum",
            period=3600,
            days=days,
        )

        avg_connections = self._get_metric_stats(
            region=region,
            namespace="AWS/RDS",
            metric_name="DatabaseConnections",
            dimensions=dimensions,
            stat="Average",
            period=3600,
            days=days,
        )

        max_connections = self._get_metric_stats(
            region=region,
            namespace="AWS/RDS",
            metric_name="DatabaseConnections",
            dimensions=dimensions,
            stat="Maximum",
            period=3600,
            days=days,
        )

        return {
            "db_instance_id": db_instance_id,
            "avg_cpu": _safe_avg(avg_cpu),
            "max_cpu": _safe_max(max_cpu),
            "avg_connections": _safe_avg(avg_connections),
            "max_connections": _safe_max(max_connections),
        }

    def get_lambda_utilization(
        self,
        function_name: str,
        region: str,
        days: int = 14,
    ) -> dict:
        """Return invocation, duration, and error metrics for a Lambda function.

        Args:
            function_name: The Lambda function name.
            region: AWS region the function runs in.
            days: Look-back window in days (default 14).

        Returns:
            Dict with keys: function_name, invocations, avg_duration_ms,
            errors.
        """
        dimensions = [{"Name": "FunctionName", "Value": function_name}]

        invocations = self._get_metric_stats(
            region=region,
            namespace="AWS/Lambda",
            metric_name="Invocations",
            dimensions=dimensions,
            stat="Sum",
            period=86400,
            days=days,
        )

        duration = self._get_metric_stats(
            region=region,
            namespace="AWS/Lambda",
            metric_name="Duration",
            dimensions=dimensions,
            stat="Average",
            period=86400,
            days=days,
        )

        errors = self._get_metric_stats(
            region=region,
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions=dimensions,
            stat="Sum",
            period=86400,
            days=days,
        )

        return {
            "function_name": function_name,
            "invocations": _safe_sum(invocations),
            "avg_duration_ms": _safe_avg(duration),
            "errors": _safe_sum(errors),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_metric_stats(
        self,
        region: str,
        namespace: str,
        metric_name: str,
        dimensions: list[dict],
        stat: str,
        period: int,
        days: int,
    ) -> list[dict] | None:
        """Retrieve CloudWatch metric statistics.

        Args:
            region: AWS region to query.
            namespace: CloudWatch namespace (e.g. ``AWS/EC2``).
            metric_name: Metric name (e.g. ``CPUUtilization``).
            dimensions: List of CloudWatch dimension filters.
            stat: Statistic type (Average, Maximum, Sum, etc.).
            period: Aggregation period in seconds.
            days: Look-back window in days.

        Returns:
            List of datapoint dicts from CloudWatch, or ``None`` on error.
        """
        end_time = datetime.now(tz=timezone.utc)
        start_time = end_time - timedelta(days=days)

        try:
            cw = self.session.client("cloudwatch", region_name=region)
            response = cw.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[stat],
            )
            return response.get("Datapoints", [])
        except ClientError as exc:
            log.warning(
                "Failed to get CloudWatch metric %s/%s for %s: %s",
                namespace,
                metric_name,
                dimensions,
                exc,
            )
            return None


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _safe_avg(datapoints: list[dict] | None) -> float | None:
    """Return the average of Average (or Sum) values across datapoints."""
    if not datapoints:
        return None
    values = [
        dp.get("Average", dp.get("Sum", 0.0))
        for dp in datapoints
        if "Average" in dp or "Sum" in dp
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _safe_max(datapoints: list[dict] | None) -> float | None:
    """Return the maximum of Maximum values across datapoints."""
    if not datapoints:
        return None
    values = [dp["Maximum"] for dp in datapoints if "Maximum" in dp]
    if not values:
        return None
    return round(max(values), 4)


def _safe_sum(datapoints: list[dict] | None) -> float | None:
    """Return the sum of Sum values across datapoints."""
    if not datapoints:
        return None
    values = [dp["Sum"] for dp in datapoints if "Sum" in dp]
    if not values:
        return None
    return round(sum(values), 4)
