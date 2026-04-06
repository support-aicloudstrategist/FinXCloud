"""Azure resource scanners for FinXCloud."""

from __future__ import annotations

import logging
from finxcloud.providers.base import CloudScanner

log = logging.getLogger(__name__)


class AzureVMScanner(CloudScanner):
    """Scan Azure Virtual Machines."""

    def __init__(self, credential, subscription_id: str):
        self._credential = credential
        self._subscription_id = subscription_id

    def scan(self) -> list[dict]:
        from azure.mgmt.compute import ComputeManagementClient

        compute = ComputeManagementClient(self._credential, self._subscription_id)
        resources = []

        for vm in compute.virtual_machines.list_all():
            resources.append({
                "resource_type": "azure_vm",
                "provider": "azure",
                "id": vm.id,
                "name": vm.name,
                "location": vm.location,
                "vm_size": vm.hardware_profile.vm_size if vm.hardware_profile else None,
                "os_type": vm.storage_profile.os_disk.os_type.value
                if vm.storage_profile and vm.storage_profile.os_disk and vm.storage_profile.os_disk.os_type
                else None,
                "provisioning_state": vm.provisioning_state,
                "tags": dict(vm.tags) if vm.tags else {},
            })

        log.info("Found %d Azure VMs", len(resources))
        return resources


class AzureDiskScanner(CloudScanner):
    """Scan Azure Managed Disks."""

    def __init__(self, credential, subscription_id: str):
        self._credential = credential
        self._subscription_id = subscription_id

    def scan(self) -> list[dict]:
        from azure.mgmt.compute import ComputeManagementClient

        compute = ComputeManagementClient(self._credential, self._subscription_id)
        resources = []

        for disk in compute.disks.list():
            resources.append({
                "resource_type": "azure_managed_disk",
                "provider": "azure",
                "id": disk.id,
                "name": disk.name,
                "location": disk.location,
                "disk_size_gb": disk.disk_size_gb,
                "sku": disk.sku.name if disk.sku else None,
                "disk_state": disk.disk_state.value if disk.disk_state else None,
                "provisioning_state": disk.provisioning_state,
                "tags": dict(disk.tags) if disk.tags else {},
            })

        log.info("Found %d Azure Managed Disks", len(resources))
        return resources


class AzureSQLScanner(CloudScanner):
    """Scan Azure SQL Databases."""

    def __init__(self, credential, subscription_id: str):
        self._credential = credential
        self._subscription_id = subscription_id

    def scan(self) -> list[dict]:
        from azure.mgmt.sql import SqlManagementClient

        sql_client = SqlManagementClient(self._credential, self._subscription_id)
        resources = []

        for server in sql_client.servers.list():
            rg = server.id.split("/")[4] if server.id else None
            if not rg:
                continue
            for db in sql_client.databases.list_by_server(rg, server.name):
                if db.name == "master":
                    continue
                resources.append({
                    "resource_type": "azure_sql_database",
                    "provider": "azure",
                    "id": db.id,
                    "name": db.name,
                    "server_name": server.name,
                    "location": db.location,
                    "sku": db.sku.name if db.sku else None,
                    "tier": db.sku.tier if db.sku else None,
                    "max_size_bytes": db.max_size_bytes,
                    "status": db.status,
                    "tags": dict(db.tags) if db.tags else {},
                })

        log.info("Found %d Azure SQL Databases", len(resources))
        return resources


class AzureStorageScanner(CloudScanner):
    """Scan Azure Storage Accounts."""

    def __init__(self, credential, subscription_id: str):
        self._credential = credential
        self._subscription_id = subscription_id

    def scan(self) -> list[dict]:
        from azure.mgmt.storage import StorageManagementClient

        storage = StorageManagementClient(self._credential, self._subscription_id)
        resources = []

        for account in storage.storage_accounts.list():
            resources.append({
                "resource_type": "azure_storage_account",
                "provider": "azure",
                "id": account.id,
                "name": account.name,
                "location": account.location,
                "sku": account.sku.name if account.sku else None,
                "kind": account.kind.value if account.kind else None,
                "access_tier": account.access_tier.value if account.access_tier else None,
                "provisioning_state": account.provisioning_state.value
                if account.provisioning_state else None,
                "tags": dict(account.tags) if account.tags else {},
            })

        log.info("Found %d Azure Storage Accounts", len(resources))
        return resources


class AzureAKSScanner(CloudScanner):
    """Scan Azure Kubernetes Service clusters."""

    def __init__(self, credential, subscription_id: str):
        self._credential = credential
        self._subscription_id = subscription_id

    def scan(self) -> list[dict]:
        from azure.mgmt.containerservice import ContainerServiceClient

        aks = ContainerServiceClient(self._credential, self._subscription_id)
        resources = []

        for cluster in aks.managed_clusters.list():
            node_pools = []
            if cluster.agent_pool_profiles:
                for pool in cluster.agent_pool_profiles:
                    node_pools.append({
                        "name": pool.name,
                        "vm_size": pool.vm_size,
                        "count": pool.count,
                        "min_count": pool.min_count,
                        "max_count": pool.max_count,
                        "os_type": pool.os_type.value if pool.os_type else None,
                    })

            resources.append({
                "resource_type": "azure_aks_cluster",
                "provider": "azure",
                "id": cluster.id,
                "name": cluster.name,
                "location": cluster.location,
                "kubernetes_version": cluster.kubernetes_version,
                "provisioning_state": cluster.provisioning_state,
                "node_pools": node_pools,
                "tags": dict(cluster.tags) if cluster.tags else {},
            })

        log.info("Found %d Azure AKS clusters", len(resources))
        return resources
