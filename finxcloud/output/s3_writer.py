"""S3 output writer for FinXCloud AWS cost optimization reports."""

import json
import logging

import boto3

log = logging.getLogger(__name__)


class S3Writer:
    """Upload report dicts to an S3 bucket."""

    def __init__(self, session: boto3.Session, bucket: str, prefix: str = "") -> None:
        self._s3 = session.client("s3")
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def _key(self, filename: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{filename}"
        return filename

    def write_json(self, report: dict, filename: str) -> str:
        """Upload a single JSON report to S3. Returns the S3 key."""
        key = self._key(filename)
        body = json.dumps(report, indent=2, default=str)
        log.info("Uploading JSON report to s3://%s/%s", self._bucket, key)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        return key

    def write_html(self, html_content: str, filename: str = "finxcloud_report.html") -> str:
        """Upload an HTML report to S3. Returns the S3 key."""
        key = self._key(filename)
        log.info("Uploading HTML report to s3://%s/%s", self._bucket, key)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=html_content.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
        )
        return key

    def write_all(
        self,
        detailed: dict,
        summary: dict,
        roadmap: dict,
        html_content: str | None = None,
    ) -> list[str]:
        """Upload all standard reports to S3. Returns the list of S3 keys."""
        keys: list[str] = [
            self.write_json(detailed, "detailed_report.json"),
            self.write_json(summary, "summary_report.json"),
            self.write_json(roadmap, "roadmap_report.json"),
        ]
        if html_content is not None:
            keys.append(self.write_html(html_content))
        log.info("All reports uploaded to s3://%s (%d files)", self._bucket, len(keys))
        return keys

    def read_json(self, filename: str) -> dict:
        """Download and parse a JSON report from S3."""
        key = self._key(filename)
        log.info("Reading JSON report from s3://%s/%s", self._bucket, key)
        resp = self._s3.get_object(Bucket=self._bucket, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))

    def list_reports(self) -> list[str]:
        """List report keys under the configured prefix."""
        prefix = f"{self._prefix}/" if self._prefix else ""
        resp = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        return [obj["Key"] for obj in resp.get("Contents", [])]
