"""GCP cloud provider for FinXCloud."""

from __future__ import annotations

import logging

from finxcloud.providers.base import (
    CloudCostAnalyzer,
    CloudProvider,
    CloudScanner,
    GCPCloudCredentials,
    ProviderRegistry,
)
from finxcloud.providers.gcp.auth import get_gcp_credentials, validate_gcp_credentials
from finxcloud.providers.gcp.scanners import (
    GCPComputeScanner,
    GCPDiskScanner,
    GCPCloudSQLScanner,
    GCPStorageScanner,
    GCPGKEScanner,
)
from finxcloud.providers.gcp.cost import GCPCostAnalyzer

log = logging.getLogger(__name__)


@ProviderRegistry.register("gcp")
class GCPProvider(CloudProvider):
    """GCP cloud provider."""

    name = "gcp"

    def __init__(self, creds: GCPCloudCredentials):
        self._creds = creds
        self._credentials, self._project_id = get_gcp_credentials(creds)

    def validate_credentials(self) -> dict:
        return validate_gcp_credentials(self._credentials, self._project_id)

    def get_scanners(self) -> list[tuple[str, CloudScanner]]:
        return [
            ("GCP Compute Instances", GCPComputeScanner(self._credentials, self._project_id)),
            ("GCP Persistent Disks", GCPDiskScanner(self._credentials, self._project_id)),
            ("GCP Cloud SQL", GCPCloudSQLScanner(self._credentials, self._project_id)),
            ("GCP Cloud Storage", GCPStorageScanner(self._credentials, self._project_id)),
            ("GCP GKE Clusters", GCPGKEScanner(self._credentials, self._project_id)),
        ]

    def get_cost_analyzer(self) -> GCPCostAnalyzer:
        return GCPCostAnalyzer(self._credentials, self._project_id)
