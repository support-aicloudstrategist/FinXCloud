"""RDS resource scanner for FinXCloud AWS cost optimization."""

import logging
from typing import Any

from botocore.exceptions import ClientError

from .base import ResourceScanner

log = logging.getLogger(__name__)


class RDSScanner(ResourceScanner):
    """Scan RDS instances and snapshots across all regions."""

    def scan(self) -> list[dict]:
        resources: list[dict] = []
        for region in self.get_regions():
            try:
                rds = self.session.client("rds", region_name=region)
                resources.extend(self._scan_instances(rds, region))
                resources.extend(self._scan_snapshots(rds, region))
            except ClientError as exc:
                log.warning("RDS scan failed in %s: %s", region, exc)
            except Exception as exc:
                log.warning("Unexpected error scanning RDS in %s: %s", region, exc)
        return resources

    # ------------------------------------------------------------------
    # RDS Instances
    # ------------------------------------------------------------------

    def _scan_instances(self, rds: Any, region: str) -> list[dict]:
        results: list[dict] = []
        paginator = rds.get_paginator("describe_db_instances")
        page_iterator = self._safe_api_call(paginator.paginate)
        if page_iterator is None:
            return results

        for page in page_iterator:
            for db in page.get("DBInstances", []):
                results.append({
                    "resource_type": "rds_instance",
                    "region": region,
                    "db_instance_id": db.get("DBInstanceIdentifier"),
                    "class": db.get("DBInstanceClass"),
                    "engine": db.get("Engine"),
                    "multi_az": db.get("MultiAZ"),
                    "storage": db.get("AllocatedStorage"),
                    "status": db.get("DBInstanceStatus"),
                })
        return results

    # ------------------------------------------------------------------
    # RDS Snapshots
    # ------------------------------------------------------------------

    def _scan_snapshots(self, rds: Any, region: str) -> list[dict]:
        results: list[dict] = []
        paginator = rds.get_paginator("describe_db_snapshots")
        page_iterator = self._safe_api_call(paginator.paginate, SnapshotType="manual")
        if page_iterator is None:
            return results

        for page in page_iterator:
            for snap in page.get("DBSnapshots", []):
                results.append({
                    "resource_type": "rds_snapshot",
                    "region": region,
                    "identifier": snap.get("DBSnapshotIdentifier"),
                    "type": snap.get("SnapshotType"),
                    "engine": snap.get("Engine"),
                    "allocated_storage": snap.get("AllocatedStorage"),
                    "create_time": snap.get("SnapshotCreateTime"),
                })
        return results
