"""EC2 resource scanner for FinXCloud AWS cost optimization."""

import logging
from typing import Any

from botocore.exceptions import ClientError

from .base import ResourceScanner

log = logging.getLogger(__name__)


class EC2Scanner(ResourceScanner):
    """Scan EC2 instances, EBS volumes, snapshots, and AMIs across all regions."""

    def scan(self) -> list[dict]:
        resources: list[dict] = []
        for region in self.get_regions():
            try:
                ec2 = self.session.client("ec2", region_name=region)
                resources.extend(self._scan_instances(ec2, region))
                resources.extend(self._scan_volumes(ec2, region))
                resources.extend(self._scan_snapshots(ec2, region))
                resources.extend(self._scan_amis(ec2, region))
            except ClientError as exc:
                log.warning("EC2 scan failed in %s: %s", region, exc)
            except Exception as exc:
                log.warning("Unexpected error scanning EC2 in %s: %s", region, exc)
        return resources

    # ------------------------------------------------------------------
    # Instances
    # ------------------------------------------------------------------

    def _scan_instances(self, ec2: Any, region: str) -> list[dict]:
        results: list[dict] = []
        paginator = ec2.get_paginator("describe_instances")
        page_iterator = self._safe_api_call(
            paginator.paginate,
            Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}],
        )
        if page_iterator is None:
            return results

        for page in page_iterator:
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    results.append({
                        "resource_type": "ec2_instance",
                        "region": region,
                        "instance_id": inst.get("InstanceId"),
                        "type": inst.get("InstanceType"),
                        "state": inst.get("State", {}).get("Name"),
                        "launch_time": inst.get("LaunchTime"),
                        "tags": {t["Key"]: t["Value"] for t in inst.get("Tags", [])},
                        "platform": inst.get("Platform", "linux"),
                        "vpc_id": inst.get("VpcId"),
                    })
        return results

    # ------------------------------------------------------------------
    # EBS Volumes
    # ------------------------------------------------------------------

    def _scan_volumes(self, ec2: Any, region: str) -> list[dict]:
        results: list[dict] = []
        paginator = ec2.get_paginator("describe_volumes")
        page_iterator = self._safe_api_call(paginator.paginate)
        if page_iterator is None:
            return results

        for page in page_iterator:
            for vol in page.get("Volumes", []):
                results.append({
                    "resource_type": "ebs_volume",
                    "region": region,
                    "volume_id": vol.get("VolumeId"),
                    "size": vol.get("Size"),
                    "type": vol.get("VolumeType"),
                    "state": vol.get("State"),
                    "attachments": [
                        {
                            "instance_id": a.get("InstanceId"),
                            "device": a.get("Device"),
                            "state": a.get("State"),
                        }
                        for a in vol.get("Attachments", [])
                    ],
                    "iops": vol.get("Iops"),
                    "encrypted": vol.get("Encrypted"),
                })
        return results

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def _scan_snapshots(self, ec2: Any, region: str) -> list[dict]:
        results: list[dict] = []
        paginator = ec2.get_paginator("describe_snapshots")
        page_iterator = self._safe_api_call(paginator.paginate, OwnerIds=["self"])
        if page_iterator is None:
            return results

        for page in page_iterator:
            for snap in page.get("Snapshots", []):
                results.append({
                    "resource_type": "ebs_snapshot",
                    "region": region,
                    "snapshot_id": snap.get("SnapshotId"),
                    "volume_size": snap.get("VolumeSize"),
                    "start_time": snap.get("StartTime"),
                    "description": snap.get("Description"),
                })
        return results

    # ------------------------------------------------------------------
    # AMIs
    # ------------------------------------------------------------------

    def _scan_amis(self, ec2: Any, region: str) -> list[dict]:
        results: list[dict] = []
        response = self._safe_api_call(ec2.describe_images, Owners=["self"])
        if response is None:
            return results

        for img in response.get("Images", []):
            results.append({
                "resource_type": "ami",
                "region": region,
                "image_id": img.get("ImageId"),
                "name": img.get("Name"),
                "creation_date": img.get("CreationDate"),
            })
        return results
