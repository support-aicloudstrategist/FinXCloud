"""Cost optimization recommendation engine for FinXCloud."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from finxcloud.analyzer.utilization import UtilizationAnalyzer

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing constants (conservative estimates, USD)
# ---------------------------------------------------------------------------
_EBS_GP2_PER_GB_MONTH: float = 0.10
_EBS_SNAPSHOT_PER_GB_MONTH: float = 0.05
_UNUSED_EIP_PER_MONTH: float = 3.65  # ~$0.005/hr * 730 hrs

# Utilization thresholds
_EC2_IDLE_CPU_THRESHOLD: float = 5.0  # percent average
_RDS_IDLE_CPU_THRESHOLD: float = 5.0
_LAMBDA_OVERSIZED_MB: int = 512

# OpenSearch pricing (conservative, USD, us-east-1)
_OPENSEARCH_HOURLY: dict[str, float] = {
    "t3.small.search": 0.036,
    "t3.medium.search": 0.073,
    "m5.large.search": 0.142,
    "m5.xlarge.search": 0.284,
    "m5.2xlarge.search": 0.568,
    "r5.large.search": 0.167,
    "r5.xlarge.search": 0.335,
    "m6g.large.search": 0.128,
    "r6g.large.search": 0.15,
}
_OPENSEARCH_DOWNSIZE_MAP: dict[str, str] = {
    "m5.xlarge.search": "m5.large.search",
    "m5.2xlarge.search": "m5.xlarge.search",
    "r5.xlarge.search": "r5.large.search",
    "m5.large.search": "t3.medium.search",
    "r5.large.search": "m5.large.search",
    "m6g.large.search": "t3.medium.search",
    "r6g.large.search": "m6g.large.search",
    "t3.medium.search": "t3.small.search",
}


class RecommendationEngine:
    """Generate cost-optimization recommendations from scanned resources.

    Args:
        resources: List of resource dicts produced by the scanners.
            Each resource dict should have at least ``resource_type``,
            ``resource_id``, and ``region`` keys. Additional keys depend
            on the resource type.
        cost_data: Summary cost data (unused today but reserved for
            future weighting of recommendations by spend).
        utilization_analyzer: Optional ``UtilizationAnalyzer`` instance
            used to fetch live CloudWatch metrics for deeper checks.
    """

    def __init__(
        self,
        resources: list[dict],
        cost_data: dict,
        utilization_analyzer: UtilizationAnalyzer | None = None,
    ) -> None:
        self.resources = resources
        self.cost_data = cost_data
        self.utilization_analyzer = utilization_analyzer
        self._recommendations: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_recommendations(self) -> list[dict]:
        """Run all checks and return recommendations sorted by savings.

        Returns:
            List of recommendation dicts sorted by
            ``estimated_monthly_savings`` descending.
        """
        self._recommendations = []

        checks = [
            self._check_idle_ec2,
            self._check_unattached_ebs,
            self._check_old_snapshots,
            self._check_unused_eips,
            self._check_oversized_rds,
            self._check_s3_lifecycle,
            self._check_idle_load_balancers,
            self._check_lambda_optimization,
            self._check_opensearch_rightsizing,
        ]

        for check in checks:
            try:
                check()
            except Exception:
                log.exception("Recommendation check %s failed", check.__name__)

        self._recommendations.sort(
            key=lambda r: r["estimated_monthly_savings"],
            reverse=True,
        )
        log.info(
            "Generated %d recommendations with total estimated savings $%.2f/mo",
            len(self._recommendations),
            sum(r["estimated_monthly_savings"] for r in self._recommendations),
        )
        return self._recommendations

    # ------------------------------------------------------------------
    # Individual checks (private)
    # ------------------------------------------------------------------

    def _check_idle_ec2(self) -> None:
        """Flag stopped EC2 instances and instances with very low CPU."""
        ec2_instances = [
            r for r in self.resources if r.get("resource_type") == "ec2_instance"
        ]

        for inst in ec2_instances:
            state = inst.get("state", "").lower()
            instance_id: str = inst.get("instance_id", inst.get("resource_id", "unknown"))
            region: str = inst.get("region", "unknown")

            # Stopped instances still incur EBS costs
            if state == "stopped":
                ebs_cost = self._estimate_ec2_ebs_cost(inst)
                self._add(
                    category="EC2",
                    title="Stopped EC2 instance still incurring EBS costs",
                    description=(
                        f"Instance {instance_id} is stopped but its attached "
                        f"EBS volumes continue to accrue charges. Consider "
                        f"creating an AMI and terminating the instance, or "
                        f"deleting unused volumes."
                    ),
                    resource_id=instance_id,
                    resource_type="ec2_instance",
                    region=region,
                    estimated_monthly_savings=ebs_cost,
                    effort_level="low",
                    priority=3,
                    well_architected_pillar="Cost Optimization",
                    action="Terminate instance or snapshot and delete volumes",
                )
                continue

            # Running instances — check CPU if utilization data is available
            if state == "running" and self.utilization_analyzer is not None:
                try:
                    util = self.utilization_analyzer.get_ec2_utilization(
                        instance_id=instance_id,
                        region=region,
                    )
                except Exception:
                    log.debug(
                        "Could not fetch utilization for %s", instance_id,
                    )
                    continue

                avg_cpu = util.get("avg_cpu")
                if avg_cpu is not None and avg_cpu < _EC2_IDLE_CPU_THRESHOLD:
                    self._add(
                        category="EC2",
                        title="Idle EC2 instance (low CPU utilization)",
                        description=(
                            f"Instance {instance_id} has an average CPU of "
                            f"{avg_cpu:.1f}% over the measurement period. "
                            f"Consider downsizing or terminating."
                        ),
                        resource_id=instance_id,
                        resource_type="ec2_instance",
                        region=region,
                        estimated_monthly_savings=self._estimate_ec2_savings(inst),
                        effort_level="medium",
                        priority=2,
                        well_architected_pillar="Cost Optimization",
                        action="Downsize or terminate instance",
                    )

    def _check_unattached_ebs(self) -> None:
        """Flag EBS volumes with state 'available' (not attached)."""
        ebs_volumes = [
            r for r in self.resources if r.get("resource_type") == "ebs_volume"
        ]

        for vol in ebs_volumes:
            if vol.get("state", "").lower() != "available":
                continue

            size_gb: float = vol.get("size", vol.get("size_gb", 0))
            volume_type: str = vol.get("type", vol.get("volume_type", "gp2"))
            vol_id: str = vol.get("volume_id", vol.get("resource_id", "unknown"))
            per_gb = _EBS_GP2_PER_GB_MONTH  # conservative default
            savings = size_gb * per_gb

            self._add(
                category="EBS",
                title="Unattached EBS volume",
                description=(
                    f"Volume {vol_id} ({volume_type}, "
                    f"{size_gb} GB) is not attached to any instance. "
                    f"Snapshot and delete to save ~${savings:.2f}/mo."
                ),
                resource_id=vol_id,
                resource_type="ebs_volume",
                region=vol.get("region", "unknown"),
                estimated_monthly_savings=savings,
                effort_level="low",
                priority=2,
                well_architected_pillar="Cost Optimization",
                action="Snapshot and delete volume",
            )

    def _check_old_snapshots(self) -> None:
        """Flag EBS snapshots older than 90 days."""
        snapshots = [
            r for r in self.resources if r.get("resource_type") == "ebs_snapshot"
        ]
        now = datetime.now(tz=timezone.utc)

        for snap in snapshots:
            created = snap.get("start_time", snap.get("created"))
            if created is None:
                continue

            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created)
                except ValueError:
                    continue

            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            age_days = (now - created).days
            if age_days < 90:
                continue

            size_gb: float = snap.get("volume_size", snap.get("size_gb", 0))
            snap_id: str = snap.get("snapshot_id", snap.get("resource_id", "unknown"))
            savings = size_gb * _EBS_SNAPSHOT_PER_GB_MONTH

            self._add(
                category="EBS",
                title="Old EBS snapshot (>90 days)",
                description=(
                    f"Snapshot {snap_id} is {age_days} days old "
                    f"({size_gb} GB). Review and delete if no longer needed "
                    f"to save ~${savings:.2f}/mo."
                ),
                resource_id=snap_id,
                resource_type="ebs_snapshot",
                region=snap.get("region", "unknown"),
                estimated_monthly_savings=savings,
                effort_level="low",
                priority=4,
                well_architected_pillar="Cost Optimization",
                action="Review and delete snapshot if unneeded",
            )

    def _check_unused_eips(self) -> None:
        """Flag Elastic IPs not associated with any instance."""
        eips = [
            r for r in self.resources if r.get("resource_type") == "elastic_ip"
        ]

        for eip in eips:
            association = eip.get("association_id") or eip.get("instance_id")
            if association:
                continue

            eip_id: str = eip.get("allocation_id", eip.get("resource_id", "unknown"))
            self._add(
                category="EC2",
                title="Unused Elastic IP address",
                description=(
                    f"Elastic IP {eip_id} "
                    f"({eip.get('public_ip', 'N/A')}) is not associated "
                    f"with a running instance. Release it to avoid "
                    f"${_UNUSED_EIP_PER_MONTH:.2f}/mo charges."
                ),
                resource_id=eip_id,
                resource_type="elastic_ip",
                region=eip.get("region", "unknown"),
                estimated_monthly_savings=_UNUSED_EIP_PER_MONTH,
                effort_level="low",
                priority=3,
                well_architected_pillar="Cost Optimization",
                action="Release Elastic IP",
            )

    def _check_oversized_rds(self) -> None:
        """Flag RDS instances with low utilization when data is available."""
        rds_instances = [
            r for r in self.resources if r.get("resource_type") == "rds_instance"
        ]

        if self.utilization_analyzer is None:
            return

        for db in rds_instances:
            db_id: str = db.get("db_instance_id", db.get("resource_id", "unknown"))
            region: str = db.get("region", "unknown")

            try:
                util = self.utilization_analyzer.get_rds_utilization(
                    db_instance_id=db_id,
                    region=region,
                )
            except Exception:
                log.debug("Could not fetch utilization for RDS %s", db_id)
                continue

            avg_cpu = util.get("avg_cpu")
            if avg_cpu is not None and avg_cpu < _RDS_IDLE_CPU_THRESHOLD:
                savings = self._estimate_rds_savings(db)
                self._add(
                    category="RDS",
                    title="Oversized or idle RDS instance",
                    description=(
                        f"RDS instance {db_id} has avg CPU of {avg_cpu:.1f}%. "
                        f"Consider downsizing the instance class or using "
                        f"Aurora Serverless."
                    ),
                    resource_id=db_id,
                    resource_type="rds_instance",
                    region=region,
                    estimated_monthly_savings=savings,
                    effort_level="high",
                    priority=2,
                    well_architected_pillar="Cost Optimization",
                    action="Downsize instance class or migrate to serverless",
                )

    def _check_s3_lifecycle(self) -> None:
        """Flag S3 buckets with zero lifecycle rules configured."""
        buckets = [
            r for r in self.resources if r.get("resource_type") == "s3_bucket"
        ]

        for bucket in buckets:
            lifecycle_count = bucket.get("lifecycle_rules_count", len(bucket.get("lifecycle_rules", [])))
            if lifecycle_count > 0:
                continue

            bucket_id: str = bucket.get("name", bucket.get("resource_id", "unknown"))
            self._add(
                category="S3",
                title="S3 bucket has no lifecycle policy",
                description=(
                    f"Bucket {bucket_id} has no lifecycle rules. "
                    f"Adding lifecycle policies to transition objects to "
                    f"cheaper storage classes or expire old objects can "
                    f"significantly reduce costs."
                ),
                resource_id=bucket_id,
                resource_type="s3_bucket",
                region=bucket.get("region", "global"),
                estimated_monthly_savings=0.0,  # cannot estimate without object data
                effort_level="medium",
                priority=4,
                well_architected_pillar="Cost Optimization",
                action="Add lifecycle rules to transition/expire objects",
            )

    def _check_idle_load_balancers(self) -> None:
        """Flag load balancers that may have no healthy targets.

        Note: The resource scan may not include target health data.
        This check flags all load balancers and recommends verifying
        target health manually.
        """
        lbs = [
            r for r in self.resources
            if r.get("resource_type") in ("elb", "alb", "nlb", "load_balancer")
        ]

        for lb in lbs:
            healthy_targets = lb.get("healthy_target_count")

            # If we have explicit health data and targets are healthy, skip
            if healthy_targets is not None and healthy_targets > 0:
                continue

            lb_id: str = lb.get("name", lb.get("arn", lb.get("resource_id", "unknown")))
            # Estimate savings: ALB ~$16.20/mo base + LCU, CLB ~$18/mo
            base_savings = 16.20
            description_suffix = ""
            if healthy_targets is not None and healthy_targets == 0:
                description_suffix = (
                    " This load balancer has 0 healthy targets."
                )
            else:
                description_suffix = (
                    " Target health data is unavailable — verify manually."
                )

            self._add(
                category="ELB",
                title="Potentially idle load balancer",
                description=(
                    f"Load balancer {lb_id} may be idle."
                    f"{description_suffix} "
                    f"Delete if no longer needed."
                ),
                resource_id=lb_id,
                resource_type=lb.get("resource_type", "load_balancer"),
                region=lb.get("region", "unknown"),
                estimated_monthly_savings=base_savings,
                effort_level="medium",
                priority=3,
                well_architected_pillar="Cost Optimization",
                action="Verify target health and delete if unused",
            )

    def _check_lambda_optimization(self) -> None:
        """Flag Lambda functions with memory > 512 MB for right-sizing."""
        lambdas = [
            r for r in self.resources if r.get("resource_type") == "lambda_function"
        ]

        for fn in lambdas:
            memory_mb: int = fn.get("memory_size", 0)
            if memory_mb <= _LAMBDA_OVERSIZED_MB:
                continue

            # Conservative savings: difference between current and 512 MB
            # at ~$0.0000166667 per GB-second, ~1M invocations, 200ms avg
            excess_gb = (memory_mb - _LAMBDA_OVERSIZED_MB) / 1024.0
            invocations = fn.get("monthly_invocations", 1_000_000)
            avg_duration_s = fn.get("avg_duration_s", 0.2)
            price_per_gb_s = 0.0000166667
            savings = excess_gb * avg_duration_s * invocations * price_per_gb_s

            fn_id: str = fn.get("name", fn.get("resource_id", "unknown"))
            self._add(
                category="Lambda",
                title="Lambda function may be over-provisioned",
                description=(
                    f"Function {fn_id} is configured with "
                    f"{memory_mb} MB memory. Review actual usage and "
                    f"consider right-sizing with AWS Lambda Power Tuning."
                ),
                resource_id=fn_id,
                resource_type="lambda_function",
                region=fn.get("region", "unknown"),
                estimated_monthly_savings=round(savings, 2),
                effort_level="low",
                priority=4,
                well_architected_pillar="Cost Optimization",
                action="Right-size memory using Lambda Power Tuning",
            )

    def _check_opensearch_rightsizing(self) -> None:
        """Flag OpenSearch domains that may be over-provisioned or could use
        reserved instances, and suggest right-sizing."""
        domains = [
            r for r in self.resources
            if r.get("resource_type") == "opensearch_domain"
        ]

        for domain in domains:
            domain_name: str = domain.get("domain_name", "unknown")
            region: str = domain.get("region", "unknown")
            instance_type: str = domain.get("instance_type", "")
            instance_count: int = domain.get("instance_count", 1)

            # Estimate current monthly cost
            current_cost = self._estimate_opensearch_cost(domain)

            # Check for right-sizing opportunity
            target_type = _OPENSEARCH_DOWNSIZE_MAP.get(instance_type)
            if target_type:
                target_hourly = _OPENSEARCH_HOURLY.get(target_type, 0)
                current_hourly = _OPENSEARCH_HOURLY.get(instance_type, 0)
                savings = (current_hourly - target_hourly) * 730 * instance_count

                self._add(
                    category="OpenSearch",
                    title="OpenSearch domain may be over-provisioned",
                    description=(
                        f"Domain {domain_name} runs {instance_count}x "
                        f"{instance_type} (est. ${current_cost:.2f}/mo). "
                        f"Consider downsizing to {target_type} to save "
                        f"~${savings:.2f}/mo. Validate with CloudWatch "
                        f"JVMMemoryPressure and CPUUtilization metrics first."
                    ),
                    resource_id=domain_name,
                    resource_type="opensearch_domain",
                    region=region,
                    estimated_monthly_savings=round(savings, 2),
                    effort_level="high",
                    priority=2,
                    well_architected_pillar="Cost Optimization",
                    action=f"Downsize data nodes from {instance_type} to {target_type}",
                )
            elif current_cost > 0:
                # No known downsize target — still flag large domains for review
                self._add(
                    category="OpenSearch",
                    title="Review OpenSearch domain configuration",
                    description=(
                        f"Domain {domain_name} runs {instance_count}x "
                        f"{instance_type} (est. ${current_cost:.2f}/mo). "
                        f"Review CloudWatch metrics and consider reserved "
                        f"instances for a ~30% discount."
                    ),
                    resource_id=domain_name,
                    resource_type="opensearch_domain",
                    region=region,
                    estimated_monthly_savings=round(current_cost * 0.30, 2),
                    effort_level="medium",
                    priority=3,
                    well_architected_pillar="Cost Optimization",
                    action="Evaluate reserved instances or Serverless migration",
                )

            # Flag dedicated master nodes if enabled — often oversized
            if domain.get("dedicated_master_enabled"):
                master_type: str = domain.get("dedicated_master_type", "")
                master_count: int = domain.get("dedicated_master_count", 3)
                master_hourly = _OPENSEARCH_HOURLY.get(master_type, 0.10)
                master_cost = master_hourly * 730 * master_count

                self._add(
                    category="OpenSearch",
                    title="Review dedicated master node sizing",
                    description=(
                        f"Domain {domain_name} has {master_count}x "
                        f"{master_type} dedicated masters (est. "
                        f"${master_cost:.2f}/mo). For clusters with fewer "
                        f"than 10 data nodes, smaller master instances "
                        f"are usually sufficient."
                    ),
                    resource_id=domain_name,
                    resource_type="opensearch_domain",
                    region=region,
                    estimated_monthly_savings=round(master_cost * 0.3, 2),
                    effort_level="medium",
                    priority=3,
                    well_architected_pillar="Cost Optimization",
                    action="Downsize dedicated master nodes",
                )

    # ------------------------------------------------------------------
    # Confidence scoring
    # ------------------------------------------------------------------

    def _compute_confidence(
        self,
        resource: dict,
        resource_type: str,
        has_utilization_data: bool = False,
    ) -> int:
        """Compute a confidence score (0-100) for a recommendation.

        Factors:
        - Data completeness: do we have utilization metrics?
        - Resource age: newer resources have less data = lower confidence
        - Utilization variance: stable = higher confidence
        """
        score = 50  # base score

        # Data completeness: utilization data available
        if has_utilization_data:
            score += 25
        else:
            score -= 10

        # Resource age — older resources have more data
        launch_time = resource.get("launch_time") or resource.get("start_time") or resource.get("created")
        if launch_time:
            if isinstance(launch_time, str):
                try:
                    launch_dt = datetime.fromisoformat(launch_time)
                except ValueError:
                    launch_dt = None
            else:
                launch_dt = launch_time

            if launch_dt:
                if launch_dt.tzinfo is None:
                    launch_dt = launch_dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(tz=timezone.utc) - launch_dt).days
                if age_days > 90:
                    score += 15
                elif age_days > 30:
                    score += 10
                elif age_days > 7:
                    score += 5
                else:
                    score -= 10  # very new, not enough data

        # Resource type confidence adjustment
        if resource_type in ("ebs_volume", "elastic_ip", "ebs_snapshot"):
            score += 10  # these are straightforward checks

        return max(0, min(100, score))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add(
        self,
        *,
        category: str,
        title: str,
        description: str,
        resource_id: str,
        resource_type: str,
        region: str,
        estimated_monthly_savings: float,
        effort_level: str,
        priority: int,
        well_architected_pillar: str,
        action: str,
        confidence_score: int | None = None,
    ) -> None:
        """Append a recommendation to the internal list."""
        # Auto-compute confidence if not provided
        if confidence_score is None:
            resource = next(
                (r for r in self.resources
                 if r.get("resource_id") == resource_id
                 or r.get("instance_id") == resource_id
                 or r.get("volume_id") == resource_id
                 or r.get("name") == resource_id
                 or r.get("db_instance_id") == resource_id
                 or r.get("domain_name") == resource_id),
                {},
            )
            has_util = self.utilization_analyzer is not None
            confidence_score = self._compute_confidence(resource, resource_type, has_util)

        rec: dict = {
            "id": str(uuid.uuid4()),
            "category": category,
            "title": title,
            "description": description,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "region": region,
            "estimated_monthly_savings": round(estimated_monthly_savings, 2),
            "effort_level": effort_level,
            "priority": priority,
            "well_architected_pillar": well_architected_pillar,
            "action": action,
            "confidence_score": confidence_score,
        }
        self._recommendations.append(rec)
        log.debug("Recommendation: %s — %s (saves $%.2f/mo, confidence %d%%)",
                   category, title, estimated_monthly_savings, confidence_score)

    @staticmethod
    def _estimate_ec2_ebs_cost(instance: dict) -> float:
        """Estimate monthly EBS cost for volumes attached to an EC2 instance."""
        volumes = instance.get("ebs_volumes", [])
        total = 0.0
        for vol in volumes:
            size_gb = vol.get("size_gb", 0)
            total += size_gb * _EBS_GP2_PER_GB_MONTH
        # Fallback: if no volume detail, assume a 30 GB root volume
        if total == 0.0:
            total = 30 * _EBS_GP2_PER_GB_MONTH
        return round(total, 2)

    @staticmethod
    def _estimate_ec2_savings(instance: dict) -> float:
        """Conservatively estimate monthly savings for a low-utilization EC2.

        Uses a rough lookup by instance family. In production this would
        query the pricing API.
        """
        instance_type: str = instance.get("type", instance.get("instance_type", ""))
        # Very rough on-demand hourly prices (USD, us-east-1)
        hourly_estimates: dict[str, float] = {
            "t2.micro": 0.0116,
            "t2.small": 0.023,
            "t2.medium": 0.0464,
            "t3.micro": 0.0104,
            "t3.small": 0.0208,
            "t3.medium": 0.0416,
            "m5.large": 0.096,
            "m5.xlarge": 0.192,
            "c5.large": 0.085,
            "r5.large": 0.126,
        }
        hourly = hourly_estimates.get(instance_type, 0.05)
        # Savings from downsizing ~50% of current cost
        return round(hourly * 730 * 0.5, 2)

    @staticmethod
    def _estimate_rds_savings(db: dict) -> float:
        """Conservatively estimate monthly savings for an idle RDS instance."""
        instance_class: str = db.get("class", db.get("instance_class", ""))
        hourly_estimates: dict[str, float] = {
            "db.t3.micro": 0.017,
            "db.t3.small": 0.034,
            "db.t3.medium": 0.068,
            "db.m5.large": 0.171,
            "db.m5.xlarge": 0.342,
            "db.r5.large": 0.24,
        }
        hourly = hourly_estimates.get(instance_class, 0.10)
        return round(hourly * 730 * 0.5, 2)

    @staticmethod
    def _estimate_opensearch_cost(domain: dict) -> float:
        """Estimate monthly cost for an OpenSearch domain (data nodes + EBS)."""
        instance_type: str = domain.get("instance_type", "")
        instance_count: int = domain.get("instance_count", 1)
        hourly = _OPENSEARCH_HOURLY.get(instance_type, 0.10)
        compute_cost = hourly * 730 * instance_count

        ebs_cost = 0.0
        if domain.get("ebs_enabled"):
            vol_size_gb: int = domain.get("ebs_volume_size_gb", 0)
            ebs_cost = vol_size_gb * instance_count * _EBS_GP2_PER_GB_MONTH

        return round(compute_cost + ebs_cost, 2)
