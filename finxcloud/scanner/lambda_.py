"""Lambda resource scanner for FinXCloud AWS cost optimization."""

import logging
from typing import Any

from botocore.exceptions import ClientError

from .base import ResourceScanner

log = logging.getLogger(__name__)


class LambdaScanner(ResourceScanner):
    """Scan Lambda functions across all regions."""

    def scan(self) -> list[dict]:
        resources: list[dict] = []
        for region in self.get_regions():
            try:
                client = self.session.client("lambda", region_name=region)
                resources.extend(self._scan_functions(client, region))
            except ClientError as exc:
                log.warning("Lambda scan failed in %s: %s", region, exc)
            except Exception as exc:
                log.warning("Unexpected error scanning Lambda in %s: %s", region, exc)
        return resources

    def _scan_functions(self, client: Any, region: str) -> list[dict]:
        results: list[dict] = []
        paginator = client.get_paginator("list_functions")
        page_iterator = self._safe_api_call(paginator.paginate)
        if page_iterator is None:
            return results

        for page in page_iterator:
            for fn in page.get("Functions", []):
                results.append({
                    "resource_type": "lambda_function",
                    "region": region,
                    "name": fn.get("FunctionName"),
                    "runtime": fn.get("Runtime"),
                    "memory_size": fn.get("MemorySize"),
                    "timeout": fn.get("Timeout"),
                    "code_size": fn.get("CodeSize"),
                    "last_modified": fn.get("LastModified"),
                    "handler": fn.get("Handler"),
                })
        return results
