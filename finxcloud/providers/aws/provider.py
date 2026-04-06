"""AWS cloud provider — wraps existing FinXCloud scanners and cost analysis."""

from __future__ import annotations

from finxcloud.auth.credentials import AWSCredentials, create_session, validate_credentials
from finxcloud.scanner.ec2 import EC2Scanner
from finxcloud.scanner.rds import RDSScanner
from finxcloud.scanner.s3 import S3Scanner
from finxcloud.scanner.lambda_ import LambdaScanner
from finxcloud.scanner.networking import NetworkingScanner
from finxcloud.scanner.opensearch import OpenSearchScanner
from finxcloud.analyzer.cost_explorer import CostExplorerAnalyzer
from finxcloud.providers.base import (
    AWSCloudCredentials,
    CloudCostAnalyzer,
    CloudProvider,
    CloudScanner,
    ProviderRegistry,
)


class AWSCostAnalyzerAdapter(CloudCostAnalyzer):
    """Adapts existing CostExplorerAnalyzer to CloudCostAnalyzer interface."""

    def __init__(self, session):
        self._ce = CostExplorerAnalyzer(session)

    def get_cost_by_service(self, days: int = 30) -> list[dict]:
        return self._ce.get_cost_by_service(days)

    def get_cost_by_region(self, days: int = 30) -> list[dict]:
        return self._ce.get_cost_by_region(days)

    def get_daily_costs(self, days: int = 30) -> list[dict]:
        return self._ce.get_daily_costs(days)

    def get_total_cost(self, days: int = 30) -> float:
        return self._ce.get_total_cost(days)

    @property
    def inner(self):
        return self._ce


@ProviderRegistry.register("aws")
class AWSProvider(CloudProvider):
    """AWS cloud provider using existing FinXCloud AWS infrastructure."""

    name = "aws"

    def __init__(self, creds: AWSCloudCredentials, regions: list[str] | None = None):
        self._creds = creds
        self._regions = regions
        aws_creds = AWSCredentials(
            access_key_id=creds.access_key_id,
            secret_access_key=creds.secret_access_key,
            session_token=creds.session_token,
            region=creds.region,
            profile=creds.profile,
            role_arn=creds.role_arn,
        )
        self._session = create_session(aws_creds)

    @property
    def session(self):
        return self._session

    def validate_credentials(self) -> dict:
        return validate_credentials(self._session)

    def get_scanners(self) -> list[tuple[str, CloudScanner]]:
        return [
            ("EC2/EBS/Snapshots", EC2Scanner(self._session, self._regions)),
            ("RDS", RDSScanner(self._session, self._regions)),
            ("S3", S3Scanner(self._session, self._regions)),
            ("Lambda", LambdaScanner(self._session, self._regions)),
            ("Networking", NetworkingScanner(self._session, self._regions)),
            ("OpenSearch", OpenSearchScanner(self._session, self._regions)),
        ]

    def get_cost_analyzer(self) -> AWSCostAnalyzerAdapter:
        return AWSCostAnalyzerAdapter(self._session)
