"""GCP authentication for FinXCloud."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def get_gcp_credentials(creds):
    """Create GCP credentials from GCPCloudCredentials.

    Returns google.oauth2 credentials object.
    """
    from google.oauth2 import service_account
    import google.auth

    if creds.use_cli:
        log.info("Using default GCP application credentials")
        credentials, project = google.auth.default()
        return credentials, project or creds.project_id

    if creds.service_account_json:
        log.info("Using GCP Service Account JSON key")
        sa_info = json.loads(creds.service_account_json)
        credentials = service_account.Credentials.from_service_account_info(sa_info)
        return credentials, creds.project_id or sa_info.get("project_id", "")

    log.info("Falling back to default GCP application credentials")
    credentials, project = google.auth.default()
    return credentials, project or creds.project_id


def validate_gcp_credentials(credentials, project_id: str) -> dict:
    """Validate GCP credentials by checking the project."""
    from google.cloud import resourcemanager_v3

    client = resourcemanager_v3.ProjectsClient(credentials=credentials)
    project = client.get_project(name=f"projects/{project_id}")
    return {
        "project_id": project.project_id,
        "display_name": project.display_name,
        "state": project.state.name if project.state else "unknown",
    }
