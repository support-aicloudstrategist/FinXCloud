"""Azure authentication for FinXCloud."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def get_azure_credential(creds):
    """Create an Azure credential object from AzureCloudCredentials.

    Returns an azure.identity credential that can be passed to Azure SDK clients.
    """
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    if creds.use_cli:
        log.info("Using default Azure CLI credentials")
        return DefaultAzureCredential()

    if creds.client_id and creds.client_secret and creds.tenant_id:
        log.info("Using Azure Service Principal credentials (tenant=%s)", creds.tenant_id)
        return ClientSecretCredential(
            tenant_id=creds.tenant_id,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
        )

    log.info("Falling back to DefaultAzureCredential")
    return DefaultAzureCredential()


def validate_azure_credentials(credential, subscription_id: str) -> dict:
    """Validate Azure credentials by listing the subscription."""
    from azure.mgmt.resource import SubscriptionClient

    sub_client = SubscriptionClient(credential)
    sub = sub_client.subscriptions.get(subscription_id)
    return {
        "subscription_id": sub.subscription_id,
        "display_name": sub.display_name,
        "state": sub.state.value if sub.state else "unknown",
        "tenant_id": sub.tenant_id,
    }
