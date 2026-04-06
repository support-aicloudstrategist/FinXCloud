"""FinXCloud Web UI — FastAPI backend wrapping existing scan logic."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from finxcloud.auth.credentials import AWSCredentials, create_session, validate_credentials
from finxcloud.auth.organizations import is_organizations_account, list_member_accounts, assume_role_session
from finxcloud.scanner.ec2 import EC2Scanner
from finxcloud.scanner.rds import RDSScanner
from finxcloud.scanner.s3 import S3Scanner
from finxcloud.scanner.lambda_ import LambdaScanner
from finxcloud.scanner.networking import NetworkingScanner
from finxcloud.scanner.opensearch import OpenSearchScanner
from finxcloud.analyzer.cost_explorer import CostExplorerAnalyzer
from finxcloud.analyzer.utilization import UtilizationAnalyzer
from finxcloud.analyzer.recommendations import RecommendationEngine
from finxcloud.reporter.detailed import DetailedReporter
from finxcloud.reporter.summary import SummaryReporter
from finxcloud.reporter.roadmap import RoadmapReporter

log = logging.getLogger("finxcloud.web")
logging.basicConfig(level=logging.INFO)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="FinXCloud Dashboard", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory scan state (PoC — single concurrent scan)
_scan_lock = threading.Lock()
_scans: dict[str, dict] = {}


class ScanRequest(BaseModel):
    access_key: str
    secret_key: str
    session_token: str | None = None
    region: str = "us-east-1"
    org_scan: bool = False
    org_role: str = "OrganizationAccountAccessRole"
    days: int = 30
    regions: str | None = None
    skip_utilization: bool = False


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/api/scan")
async def start_scan(req: ScanRequest):
    scan_id = str(uuid.uuid4())[:8]
    _scans[scan_id] = {"status": "running", "progress": "Initializing...", "result": None, "error": None}
    thread = threading.Thread(target=_run_scan, args=(scan_id, req), daemon=True)
    thread.start()
    return {"scan_id": scan_id, "status": "running"}


@app.get("/api/scan/{scan_id}")
async def get_scan_status(scan_id: str):
    scan = _scans.get(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {
        "scan_id": scan_id,
        "status": scan["status"],
        "progress": scan["progress"],
        "error": scan["error"],
    }


@app.get("/api/scan/{scan_id}/results")
async def get_scan_results(scan_id: str):
    scan = _scans.get(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan["status"] == "running":
        raise HTTPException(status_code=202, detail="Scan still running")
    if scan["status"] == "failed":
        raise HTTPException(status_code=500, detail=scan["error"])
    return scan["result"]


def _run_scan(scan_id: str, req: ScanRequest) -> None:
    """Execute the full scan pipeline in a background thread."""
    scan = _scans[scan_id]
    try:
        # Parse regions
        region_list = [r.strip() for r in req.regions.split(",")] if req.regions else None

        # Authenticate
        scan["progress"] = "Validating AWS credentials..."
        creds = AWSCredentials(
            access_key_id=req.access_key,
            secret_access_key=req.secret_key,
            session_token=req.session_token,
            region=req.region,
        )
        session = create_session(creds)
        identity = validate_credentials(session)

        # Determine accounts
        import boto3
        accounts_to_scan: list[tuple[str, boto3.Session]] = []
        if req.org_scan:
            scan["progress"] = "Discovering Organization accounts..."
            if is_organizations_account(session):
                members = list_member_accounts(session)
                for member in members:
                    try:
                        member_session = assume_role_session(session, member["id"], req.org_role, req.region)
                        accounts_to_scan.append((member["id"], member_session))
                    except Exception:
                        log.warning("Could not assume role in %s", member["id"])

        if not accounts_to_scan:
            account_id = identity.get("Account", "unknown")
            accounts_to_scan.append((account_id, session))

        # Scan resources
        all_resources: list[dict] = []
        all_cost_data: dict = {}

        for account_id, acct_session in accounts_to_scan:
            scan["progress"] = f"Scanning resources in account {account_id}..."
            scanners = [
                ("EC2/EBS/Snapshots", EC2Scanner(acct_session, region_list)),
                ("RDS", RDSScanner(acct_session, region_list)),
                ("S3", S3Scanner(acct_session, region_list)),
                ("Lambda", LambdaScanner(acct_session, region_list)),
                ("Networking", NetworkingScanner(acct_session, region_list)),
                ("OpenSearch", OpenSearchScanner(acct_session, region_list)),
            ]

            for name, scanner in scanners:
                scan["progress"] = f"Scanning {name} in {account_id}..."
                try:
                    resources = scanner.scan()
                    for r in resources:
                        r["account_id"] = account_id
                    all_resources.extend(resources)
                except Exception:
                    log.exception("Scanner %s failed for %s", name, account_id)

            # Cost Explorer
            scan["progress"] = f"Pulling Cost Explorer data for {account_id}..."
            try:
                ce = CostExplorerAnalyzer(acct_session)
                all_cost_data[account_id] = {
                    "by_service": ce.get_cost_by_service(req.days),
                    "by_region": ce.get_cost_by_region(req.days),
                    "by_account": ce.get_cost_by_account(req.days),
                    "daily_trend": ce.get_daily_costs(req.days),
                    "total_cost_30d": ce.get_total_cost(req.days),
                }
            except Exception:
                log.exception("Cost Explorer failed for %s", account_id)
                all_cost_data[account_id] = {
                    "by_service": [], "by_region": [], "by_account": [],
                    "daily_trend": [], "total_cost_30d": 0.0,
                }

        # Merge cost data
        merged_cost_data = _merge_cost_data(all_cost_data)

        # Utilization
        utilization_analyzer = None
        if not req.skip_utilization:
            scan["progress"] = "Collecting utilization metrics..."
            utilization_analyzer = UtilizationAnalyzer(session)

        # Recommendations
        scan["progress"] = "Generating recommendations..."
        engine = RecommendationEngine(all_resources, merged_cost_data, utilization_analyzer)
        recommendations = engine.generate_recommendations()

        # Reports
        scan["progress"] = "Building reports..."
        detailed_reporter = DetailedReporter(all_resources, merged_cost_data)
        detailed_report = detailed_reporter.generate()

        summary_reporter = SummaryReporter(detailed_report, recommendations)
        summary_report = summary_reporter.generate()

        roadmap_reporter = RoadmapReporter(recommendations)
        roadmap_report = roadmap_reporter.generate()

        scan["result"] = {
            "summary": summary_report,
            "detailed": detailed_report,
            "roadmap": roadmap_report,
            "recommendations": recommendations,
            "resources": all_resources,
            "cost_data": merged_cost_data,
        }
        scan["status"] = "done"
        scan["progress"] = "Scan complete"

    except Exception as e:
        log.exception("Scan %s failed", scan_id)
        scan["status"] = "failed"
        scan["error"] = str(e)
        scan["progress"] = f"Failed: {e}"


def _merge_cost_data(cost_data_by_account: dict) -> dict:
    """Merge cost data from multiple accounts."""
    if len(cost_data_by_account) == 1:
        return next(iter(cost_data_by_account.values()))

    merged = {
        "by_service": [], "by_region": [], "by_account": [],
        "daily_trend": [], "total_cost_30d": 0.0,
    }
    service_totals: dict[str, float] = {}
    region_totals: dict[str, float] = {}
    daily_totals: dict[str, float] = {}

    for account_id, data in cost_data_by_account.items():
        merged["total_cost_30d"] += data.get("total_cost_30d", 0.0)
        merged["by_account"].append({
            "account": account_id, "amount": data.get("total_cost_30d", 0.0),
            "unit": "USD", "currency": "USD",
        })
        for entry in data.get("by_service", []):
            service_totals[entry["service"]] = service_totals.get(entry["service"], 0) + float(entry["amount"])
        for entry in data.get("by_region", []):
            region_totals[entry.get("region", "unknown")] = region_totals.get(entry.get("region", "unknown"), 0) + float(entry["amount"])
        for entry in data.get("daily_trend", []):
            daily_totals[entry["date"]] = daily_totals.get(entry["date"], 0) + float(entry["amount"])

    merged["by_service"] = [
        {"service": k, "amount": v, "unit": "USD", "currency": "USD"}
        for k, v in sorted(service_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    merged["by_region"] = [
        {"region": k, "amount": v, "unit": "USD", "currency": "USD"}
        for k, v in sorted(region_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    merged["daily_trend"] = [
        {"date": k, "amount": v} for k, v in sorted(daily_totals.items())
    ]
    return merged
