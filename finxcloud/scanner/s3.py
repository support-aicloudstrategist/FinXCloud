"""S3 resource scanner for FinXCloud AWS cost optimization."""

import logging

from botocore.exceptions import ClientError

from .base import ResourceScanner

log = logging.getLogger(__name__)


class S3Scanner(ResourceScanner):
    """Scan S3 buckets and their configurations (global service)."""

    def scan(self) -> list[dict]:
        resources: list[dict] = []
        s3 = self.session.client("s3")

        try:
            response = self._safe_api_call(s3.list_buckets)
        except ClientError as exc:
            log.warning("S3 list_buckets failed: %s", exc)
            return resources

        if response is None:
            return resources

        for bucket in response.get("Buckets", []):
            name = bucket.get("Name", "")
            record: dict = {
                "resource_type": "s3_bucket",
                "name": name,
                "creation_date": bucket.get("CreationDate"),
                "region": self._get_bucket_region(s3, name),
                "versioning": self._get_versioning(s3, name),
                "lifecycle_rules_count": self._get_lifecycle_rules_count(s3, name),
                "encryption": self._get_encryption(s3, name),
            }
            resources.append(record)

        return resources

    # ------------------------------------------------------------------
    # Per-bucket configuration helpers
    # ------------------------------------------------------------------

    def _get_bucket_region(self, s3, bucket_name: str) -> str:
        try:
            resp = self._safe_api_call(s3.get_bucket_location, Bucket=bucket_name)
            if resp is None:
                return "unknown"
            # LocationConstraint is None for us-east-1
            return resp.get("LocationConstraint") or "us-east-1"
        except ClientError as exc:
            log.warning("Failed to get location for bucket %s: %s", bucket_name, exc)
            return "unknown"

    def _get_versioning(self, s3, bucket_name: str) -> str:
        try:
            resp = self._safe_api_call(s3.get_bucket_versioning, Bucket=bucket_name)
            if resp is None:
                return "unknown"
            return resp.get("Status", "Disabled")
        except ClientError as exc:
            log.warning("Failed to get versioning for bucket %s: %s", bucket_name, exc)
            return "unknown"

    def _get_lifecycle_rules_count(self, s3, bucket_name: str) -> int:
        try:
            resp = self._safe_api_call(
                s3.get_bucket_lifecycle_configuration, Bucket=bucket_name,
            )
            if resp is None:
                return 0
            return len(resp.get("Rules", []))
        except ClientError as exc:
            error_code = exc.response["Error"].get("Code", "")
            if error_code == "NoSuchLifecycleConfiguration":
                return 0
            log.warning("Failed to get lifecycle for bucket %s: %s", bucket_name, exc)
            return 0

    def _get_encryption(self, s3, bucket_name: str) -> str | None:
        try:
            resp = self._safe_api_call(
                s3.get_bucket_encryption, Bucket=bucket_name,
            )
            if resp is None:
                return None
            rules = resp.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            if rules:
                return rules[0].get("ApplyServerSideEncryptionByDefault", {}).get(
                    "SSEAlgorithm"
                )
            return None
        except ClientError as exc:
            error_code = exc.response["Error"].get("Code", "")
            if error_code == "ServerSideEncryptionConfigurationNotFoundError":
                return None
            log.warning("Failed to get encryption for bucket %s: %s", bucket_name, exc)
            return None
