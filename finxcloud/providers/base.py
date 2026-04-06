"""Base cloud provider abstraction for multi-cloud support."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class CloudCredentials:
    """Base credentials container for any cloud provider."""

    provider: str
    region: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AWSCloudCredentials(CloudCredentials):
    """AWS-specific credentials."""

    provider: str = "aws"
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str | None = None
    region: str = "us-east-1"
    profile: str | None = None
    role_arn: str | None = None


@dataclass
class AzureCloudCredentials(CloudCredentials):
    """Azure-specific credentials."""

    provider: str = "azure"
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    subscription_id: str = ""
    region: str = "eastus"
    use_cli: bool = False


@dataclass
class GCPCloudCredentials(CloudCredentials):
    """GCP-specific credentials."""

    provider: str = "gcp"
    project_id: str = ""
    service_account_json: str = ""
    region: str = "us-central1"
    use_cli: bool = False


class CloudScanner(ABC):
    """Abstract base class for all cloud resource scanners."""

    MAX_RETRIES: int = 3
    INITIAL_BACKOFF: float = 1.0

    @abstractmethod
    def scan(self) -> list[dict]:
        """Scan cloud resources and return a list of resource dicts."""
        ...

    def _retry_api_call(self, func, retryable_exceptions=(), **kwargs):
        """Wrap an API call with retry/exponential backoff."""
        backoff = self.INITIAL_BACKOFF
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return func(**kwargs)
            except retryable_exceptions as exc:
                if attempt < self.MAX_RETRIES:
                    log.warning(
                        "API call %s failed (attempt %d/%d), retrying in %.1fs: %s",
                        func.__name__, attempt, self.MAX_RETRIES, backoff, exc,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise
        return None


class CloudCostAnalyzer(ABC):
    """Abstract base for cloud cost analysis."""

    @abstractmethod
    def get_cost_by_service(self, days: int = 30) -> list[dict]:
        ...

    @abstractmethod
    def get_cost_by_region(self, days: int = 30) -> list[dict]:
        ...

    @abstractmethod
    def get_daily_costs(self, days: int = 30) -> list[dict]:
        ...

    @abstractmethod
    def get_total_cost(self, days: int = 30) -> float:
        ...


class CloudProvider(ABC):
    """Abstract cloud provider that creates scanners and cost analyzers."""

    name: str = ""

    @abstractmethod
    def validate_credentials(self) -> dict:
        """Validate credentials and return identity info."""
        ...

    @abstractmethod
    def get_scanners(self) -> list[tuple[str, CloudScanner]]:
        """Return list of (name, scanner) tuples for this provider."""
        ...

    @abstractmethod
    def get_cost_analyzer(self) -> CloudCostAnalyzer | None:
        """Return a cost analyzer for this provider, or None if unavailable."""
        ...


class ProviderRegistry:
    """Registry of available cloud providers."""

    _providers: dict[str, type[CloudProvider]] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(provider_cls: type[CloudProvider]):
            cls._providers[name] = provider_cls
            return provider_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> type[CloudProvider] | None:
        return cls._providers.get(name)

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._providers.keys())
