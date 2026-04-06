"""Base scanner module for FinXCloud AWS cost optimization."""

import logging
import time
from abc import ABC, abstractmethod

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


class ResourceScanner(ABC):
    """Abstract base class for all AWS resource scanners."""

    MAX_RETRIES: int = 3
    INITIAL_BACKOFF: float = 1.0
    THROTTLE_CODES: set[str] = {"Throttling", "RequestLimitExceeded"}

    def __init__(self, session: boto3.Session, regions: list[str] | None = None) -> None:
        self.session = session
        self.regions = regions

    @abstractmethod
    def scan(self) -> list[dict]:
        """Scan AWS resources and return a list of resource dicts."""
        ...

    def get_regions(self) -> list[str]:
        """Return configured regions or discover all enabled regions via EC2."""
        if self.regions:
            return self.regions

        ec2 = self.session.client("ec2")
        response = self._safe_api_call(ec2.describe_regions, Filters=[
            {"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]},
        ])
        if response is None:
            log.warning("Failed to discover regions, falling back to session region")
            return [self.session.region_name or "us-east-1"]

        return [r["RegionName"] for r in response.get("Regions", [])]

    def _safe_api_call(self, func, **kwargs):
        """Wrap an AWS API call with retry/exponential backoff for throttling.

        Returns the API response on success, or None after all retries are
        exhausted or on a non-throttle error.
        """
        backoff = self.INITIAL_BACKOFF
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return func(**kwargs)
            except ClientError as exc:
                error_code = exc.response["Error"].get("Code", "")
                if error_code in self.THROTTLE_CODES and attempt < self.MAX_RETRIES:
                    log.warning(
                        "Throttled on %s (attempt %d/%d), retrying in %.1fs",
                        func.__name__, attempt, self.MAX_RETRIES, backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise
        return None  # pragma: no cover
