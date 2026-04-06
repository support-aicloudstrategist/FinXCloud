"""Azure cloud provider for FinXCloud."""

from __future__ import annotations

import logging

from finxcloud.providers.base import (
    AzureCloudCredentials,
    CloudCostAnalyzer,
    CloudProvider,
    CloudScanner,
    ProviderRegistry,
)
from finxcloud.providers.azure.auth import get_azure_credential, validate_azure_credentials
from finxcloud.providers.azure.scanners import (
    AzureVMScanner,
    AzureDiskScanner,
    AzureSQLScanner,
    AzureStorageScanner,
    AzureAKSScanner,
)
from finxcloud.providers.azure.cost import AzureCostAnalyzer

log = logging.getLogger(__name__)


@ProviderRegistry.register("azure")
class AzureProvider(CloudProvider):
    """Azure cloud provider."""

    name = "azure"

    def __init__(self, creds: AzureCloudCredentials):
        self._creds = creds
        self._credential = get_azure_credential(creds)
        self._subscription_id = creds.subscription_id

    def validate_credentials(self) -> dict:
        return validate_azure_credentials(self._credential, self._subscription_id)

    def get_scanners(self) -> list[tuple[str, CloudScanner]]:
        return [
            ("Azure VMs", AzureVMScanner(self._credential, self._subscription_id)),
            ("Azure Managed Disks", AzureDiskScanner(self._credential, self._subscription_id)),
            ("Azure SQL Databases", AzureSQLScanner(self._credential, self._subscription_id)),
            ("Azure Storage Accounts", AzureStorageScanner(self._credential, self._subscription_id)),
            ("Azure AKS Clusters", AzureAKSScanner(self._credential, self._subscription_id)),
        ]

    def get_cost_analyzer(self) -> AzureCostAnalyzer:
        return AzureCostAnalyzer(self._credential, self._subscription_id)
