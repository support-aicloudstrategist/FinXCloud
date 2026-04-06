"""GCP resource scanners for FinXCloud."""

from __future__ import annotations

import logging
from finxcloud.providers.base import CloudScanner

log = logging.getLogger(__name__)


class GCPComputeScanner(CloudScanner):
    """Scan GCP Compute Engine VMs."""

    def __init__(self, credentials, project_id: str):
        self._credentials = credentials
        self._project_id = project_id

    def scan(self) -> list[dict]:
        from google.cloud import compute_v1

        client = compute_v1.InstancesClient(credentials=self._credentials)
        resources = []

        request = compute_v1.AggregatedListInstancesRequest(project=self._project_id)
        for zone, instances_scoped in client.aggregated_list(request=request):
            if not instances_scoped.instances:
                continue
            for vm in instances_scoped.instances:
                resources.append({
                    "resource_type": "gcp_compute_instance",
                    "provider": "gcp",
                    "id": str(vm.id),
                    "name": vm.name,
                    "zone": zone.split("/")[-1] if "/" in zone else zone,
                    "machine_type": vm.machine_type.split("/")[-1] if vm.machine_type else None,
                    "status": vm.status,
                    "tags": dict(vm.labels) if vm.labels else {},
                })

        log.info("Found %d GCP Compute instances", len(resources))
        return resources


class GCPDiskScanner(CloudScanner):
    """Scan GCP Persistent Disks."""

    def __init__(self, credentials, project_id: str):
        self._credentials = credentials
        self._project_id = project_id

    def scan(self) -> list[dict]:
        from google.cloud import compute_v1

        client = compute_v1.DisksClient(credentials=self._credentials)
        resources = []

        request = compute_v1.AggregatedListDisksRequest(project=self._project_id)
        for zone, disks_scoped in client.aggregated_list(request=request):
            if not disks_scoped.disks:
                continue
            for disk in disks_scoped.disks:
                resources.append({
                    "resource_type": "gcp_persistent_disk",
                    "provider": "gcp",
                    "id": str(disk.id),
                    "name": disk.name,
                    "zone": zone.split("/")[-1] if "/" in zone else zone,
                    "size_gb": int(disk.size_gb) if disk.size_gb else None,
                    "type": disk.type_.split("/")[-1] if disk.type_ else None,
                    "status": disk.status,
                    "users": list(disk.users) if disk.users else [],
                    "tags": dict(disk.labels) if disk.labels else {},
                })

        log.info("Found %d GCP Persistent Disks", len(resources))
        return resources


class GCPCloudSQLScanner(CloudScanner):
    """Scan GCP Cloud SQL instances."""

    def __init__(self, credentials, project_id: str):
        self._credentials = credentials
        self._project_id = project_id

    def scan(self) -> list[dict]:
        from googleapiclient.discovery import build

        service = build("sqladmin", "v1beta4", credentials=self._credentials)
        resources = []

        result = service.instances().list(project=self._project_id).execute()
        for instance in result.get("items", []):
            settings = instance.get("settings", {})
            resources.append({
                "resource_type": "gcp_cloud_sql",
                "provider": "gcp",
                "id": instance.get("name", ""),
                "name": instance.get("name", ""),
                "region": instance.get("region", ""),
                "database_version": instance.get("databaseVersion", ""),
                "tier": settings.get("tier", ""),
                "data_disk_size_gb": settings.get("dataDiskSizeGb"),
                "data_disk_type": settings.get("dataDiskType", ""),
                "state": instance.get("state", ""),
                "tags": settings.get("userLabels", {}),
            })

        log.info("Found %d GCP Cloud SQL instances", len(resources))
        return resources


class GCPStorageScanner(CloudScanner):
    """Scan GCP Cloud Storage buckets."""

    def __init__(self, credentials, project_id: str):
        self._credentials = credentials
        self._project_id = project_id

    def scan(self) -> list[dict]:
        from google.cloud import storage

        client = storage.Client(project=self._project_id, credentials=self._credentials)
        resources = []

        for bucket in client.list_buckets():
            resources.append({
                "resource_type": "gcp_storage_bucket",
                "provider": "gcp",
                "id": bucket.name,
                "name": bucket.name,
                "location": bucket.location,
                "storage_class": bucket.storage_class,
                "versioning_enabled": bucket.versioning_enabled,
                "tags": dict(bucket.labels) if bucket.labels else {},
            })

        log.info("Found %d GCP Storage buckets", len(resources))
        return resources


class GCPGKEScanner(CloudScanner):
    """Scan GCP Google Kubernetes Engine clusters."""

    def __init__(self, credentials, project_id: str):
        self._credentials = credentials
        self._project_id = project_id

    def scan(self) -> list[dict]:
        from google.cloud import container_v1

        client = container_v1.ClusterManagerClient(credentials=self._credentials)
        resources = []

        parent = f"projects/{self._project_id}/locations/-"
        response = client.list_clusters(parent=parent)

        for cluster in response.clusters:
            node_pools = []
            for pool in (cluster.node_pools or []):
                node_pools.append({
                    "name": pool.name,
                    "machine_type": pool.config.machine_type if pool.config else None,
                    "disk_size_gb": pool.config.disk_size_gb if pool.config else None,
                    "node_count": pool.initial_node_count,
                    "autoscaling_min": pool.autoscaling.min_node_count if pool.autoscaling else None,
                    "autoscaling_max": pool.autoscaling.max_node_count if pool.autoscaling else None,
                })

            resources.append({
                "resource_type": "gcp_gke_cluster",
                "provider": "gcp",
                "id": cluster.name,
                "name": cluster.name,
                "location": cluster.location,
                "status": cluster.status.name if cluster.status else None,
                "current_master_version": cluster.current_master_version,
                "node_pools": node_pools,
                "tags": dict(cluster.resource_labels) if cluster.resource_labels else {},
            })

        log.info("Found %d GCP GKE clusters", len(resources))
        return resources
