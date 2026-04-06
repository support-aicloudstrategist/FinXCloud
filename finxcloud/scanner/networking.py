"""Networking resource scanner for FinXCloud AWS cost optimization."""

import logging
from typing import Any

from botocore.exceptions import ClientError

from .base import ResourceScanner

log = logging.getLogger(__name__)


class NetworkingScanner(ResourceScanner):
    """Scan Elastic IPs, NAT Gateways, and Load Balancers across all regions."""

    def scan(self) -> list[dict]:
        resources: list[dict] = []
        for region in self.get_regions():
            try:
                ec2 = self.session.client("ec2", region_name=region)
                elbv2 = self.session.client("elbv2", region_name=region)
                resources.extend(self._scan_elastic_ips(ec2, region))
                resources.extend(self._scan_nat_gateways(ec2, region))
                resources.extend(self._scan_load_balancers(elbv2, region))
            except ClientError as exc:
                log.warning("Networking scan failed in %s: %s", region, exc)
            except Exception as exc:
                log.warning("Unexpected error scanning networking in %s: %s", region, exc)
        return resources

    # ------------------------------------------------------------------
    # Elastic IPs
    # ------------------------------------------------------------------

    def _scan_elastic_ips(self, ec2: Any, region: str) -> list[dict]:
        results: list[dict] = []
        try:
            response = self._safe_api_call(ec2.describe_addresses)
            if response is None:
                return results

            for addr in response.get("Addresses", []):
                results.append({
                    "resource_type": "elastic_ip",
                    "region": region,
                    "allocation_id": addr.get("AllocationId"),
                    "public_ip": addr.get("PublicIp"),
                    "association_id": addr.get("AssociationId"),
                    "instance_id": addr.get("InstanceId"),
                })
        except ClientError as exc:
            log.warning("Failed to scan Elastic IPs in %s: %s", region, exc)
        return results

    # ------------------------------------------------------------------
    # NAT Gateways
    # ------------------------------------------------------------------

    def _scan_nat_gateways(self, ec2: Any, region: str) -> list[dict]:
        results: list[dict] = []
        try:
            paginator = ec2.get_paginator("describe_nat_gateways")
            page_iterator = self._safe_api_call(paginator.paginate)
            if page_iterator is None:
                return results

            for page in page_iterator:
                for ngw in page.get("NatGateways", []):
                    results.append({
                        "resource_type": "nat_gateway",
                        "region": region,
                        "id": ngw.get("NatGatewayId"),
                        "state": ngw.get("State"),
                        "subnet_id": ngw.get("SubnetId"),
                        "vpc_id": ngw.get("VpcId"),
                    })
        except ClientError as exc:
            log.warning("Failed to scan NAT Gateways in %s: %s", region, exc)
        return results

    # ------------------------------------------------------------------
    # Load Balancers (ELBv2)
    # ------------------------------------------------------------------

    def _scan_load_balancers(self, elbv2: Any, region: str) -> list[dict]:
        results: list[dict] = []
        try:
            paginator = elbv2.get_paginator("describe_load_balancers")
            page_iterator = self._safe_api_call(paginator.paginate)
            if page_iterator is None:
                return results

            for page in page_iterator:
                for lb in page.get("LoadBalancers", []):
                    results.append({
                        "resource_type": "load_balancer",
                        "region": region,
                        "arn": lb.get("LoadBalancerArn"),
                        "name": lb.get("LoadBalancerName"),
                        "type": lb.get("Type"),
                        "scheme": lb.get("Scheme"),
                        "state": lb.get("State", {}).get("Code"),
                    })
        except ClientError as exc:
            log.warning("Failed to scan Load Balancers in %s: %s", region, exc)
        return results
