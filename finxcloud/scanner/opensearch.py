"""OpenSearch resource scanner for FinXCloud AWS cost optimization."""

import logging
from typing import Any

from botocore.exceptions import ClientError

from .base import ResourceScanner

log = logging.getLogger(__name__)


class OpenSearchScanner(ResourceScanner):
    """Scan OpenSearch domains across all regions."""

    def scan(self) -> list[dict]:
        resources: list[dict] = []
        for region in self.get_regions():
            try:
                client = self.session.client("opensearch", region_name=region)
                resources.extend(self._scan_domains(client, region))
            except ClientError as exc:
                log.warning("OpenSearch scan failed in %s: %s", region, exc)
            except Exception as exc:
                log.warning("Unexpected error scanning OpenSearch in %s: %s", region, exc)
        return resources

    def _scan_domains(self, client: Any, region: str) -> list[dict]:
        results: list[dict] = []

        # List all domain names in this region
        list_resp = self._safe_api_call(client.list_domain_names)
        if list_resp is None:
            return results

        domain_names = [d["DomainName"] for d in list_resp.get("DomainNames", [])]
        if not domain_names:
            return results

        # Describe all domains in a single batch call
        desc_resp = self._safe_api_call(
            client.describe_domains, DomainNames=domain_names,
        )
        if desc_resp is None:
            return results

        for domain in desc_resp.get("DomainStatusList", []):
            cluster_config = domain.get("ClusterConfig", {})
            ebs_options = domain.get("EBSOptions", {})

            results.append({
                "resource_type": "opensearch_domain",
                "region": region,
                "domain_name": domain.get("DomainName"),
                "domain_id": domain.get("DomainId"),
                "arn": domain.get("ARN"),
                "engine_version": domain.get("EngineVersion"),
                "instance_type": cluster_config.get("InstanceType"),
                "instance_count": cluster_config.get("InstanceCount", 1),
                "dedicated_master_enabled": cluster_config.get("DedicatedMasterEnabled", False),
                "dedicated_master_type": cluster_config.get("DedicatedMasterType"),
                "dedicated_master_count": cluster_config.get("DedicatedMasterCount", 0),
                "warm_enabled": cluster_config.get("WarmEnabled", False),
                "warm_type": cluster_config.get("WarmType"),
                "warm_count": cluster_config.get("WarmCount", 0),
                "zone_awareness_enabled": cluster_config.get("ZoneAwarenessEnabled", False),
                "ebs_enabled": ebs_options.get("EBSEnabled", False),
                "ebs_volume_type": ebs_options.get("VolumeType"),
                "ebs_volume_size_gb": ebs_options.get("VolumeSize", 0),
                "ebs_iops": ebs_options.get("Iops"),
                "ebs_throughput": ebs_options.get("Throughput"),
                "endpoint": domain.get("Endpoint") or domain.get("Endpoints", {}).get("vpc"),
                "processing": domain.get("Processing", False),
                "deleted": domain.get("Deleted", False),
            })

        return results
