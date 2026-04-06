"""FinXCloud Web UI — FastAPI backend wrapping existing scan logic."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from finxcloud.web.auth import authenticate, require_auth
from finxcloud.web.storage import (
    create_account,
    delete_account,
    get_account,
    get_latest_scan,
    list_accounts,
    list_scans,
    save_scan_result,
    update_account,
)
from finxcloud.auth.credentials import AWSCredentials, create_session, validate_credentials
from finxcloud.output.s3_writer import S3Writer
from finxcloud.auth.organizations import is_organizations_account, list_member_accounts, assume_role_session
from finxcloud.scanner.ec2 import EC2Scanner
from finxcloud.scanner.rds import RDSScanner
from finxcloud.scanner.s3 import S3Scanner
from finxcloud.scanner.lambda_ import LambdaScanner
from finxcloud.scanner.networking import NetworkingScanner
from finxcloud.scanner.opensearch import OpenSearchScanner
from finxcloud.analyzer.anomaly import AnomalyDetector
from finxcloud.analyzer.budget import BudgetTracker
from finxcloud.analyzer.commitments import CommitmentsAnalyzer
from finxcloud.analyzer.cost_explorer import CostExplorerAnalyzer
from finxcloud.analyzer.utilization import UtilizationAnalyzer
from finxcloud.analyzer.recommendations import RecommendationEngine
from finxcloud.reporter.detailed import DetailedReporter
from finxcloud.reporter.summary import SummaryReporter
from finxcloud.reporter.roadmap import RoadmapReporter

log = logging.getLogger("finxcloud.web")
logging.basicConfig(level=logging.INFO)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="FinXCloud Dashboard", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory scan state (PoC — single concurrent scan)
_scan_lock = threading.Lock()
_scans: dict[str, dict] = {}


class LoginRequest(BaseModel):
    username: str
    password: str


class ScanRequest(BaseModel):
    provider: str = "aws"
    access_key: str = ""
    secret_key: str = ""
    session_token: str | None = None
    region: str = "us-east-1"
    role_arn: str | None = None
    org_scan: bool = False
    org_role: str = "OrganizationAccountAccessRole"
    days: int = 30
    regions: str | None = None
    skip_utilization: bool = False
    output_s3_bucket: str | None = None
    output_s3_prefix: str = ""
    stored_account_id: str | None = None
    allocation_tags: str | None = None
    # Azure fields
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_subscription_id: str | None = None
    # GCP fields
    gcp_project_id: str | None = None
    gcp_service_account_json: str | None = None


class AccountRequest(BaseModel):
    name: str
    provider: str = "aws"
    access_key: str = ""
    secret_key: str = ""
    region: str = "us-east-1"
    role_arn: str | None = None
    org_scan: bool = False
    # Azure fields
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_subscription_id: str | None = None
    # GCP fields
    gcp_project_id: str | None = None
    gcp_service_account_json: str | None = None


class AccountUpdateRequest(BaseModel):
    name: str | None = None
    provider: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    region: str | None = None
    role_arn: str | None = None
    org_scan: bool | None = None
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    azure_subscription_id: str | None = None
    gcp_project_id: str | None = None
    gcp_service_account_json: str | None = None


class EmailReportRequest(BaseModel):
    to_addresses: list[str]
    subject: str | None = None
    scan_id: str | None = None
    account_id: str | None = None
    method: str = "ses"
    from_address: str | None = None
    aws_access_key: str | None = None
    aws_secret_key: str | None = None
    aws_region: str | None = None


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/api/login")
async def login(req: LoginRequest):
    token = authenticate(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    response = JSONResponse({"status": "ok", "username": req.username})
    response.set_cookie(
        key="finxcloud_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=24 * 3600,
    )
    return response


@app.post("/api/logout")
async def logout():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie("finxcloud_token")
    return response


@app.get("/api/me")
async def me(user: dict = Depends(require_auth)):
    return {"username": user["sub"]}


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------

@app.get("/api/accounts")
async def api_list_accounts(_user: dict = Depends(require_auth)):
    return list_accounts()


@app.post("/api/accounts")
async def api_create_account(req: AccountRequest, _user: dict = Depends(require_auth)):
    provider_creds = {}
    if req.provider == "azure":
        provider_creds = {
            "tenant_id": req.azure_tenant_id or "",
            "client_id": req.azure_client_id or "",
            "client_secret": req.azure_client_secret or "",
            "subscription_id": req.azure_subscription_id or "",
        }
    elif req.provider == "gcp":
        provider_creds = {
            "project_id": req.gcp_project_id or "",
            "service_account_json": req.gcp_service_account_json or "",
        }
    acct = create_account(
        name=req.name,
        access_key=req.access_key,
        secret_key=req.secret_key,
        region=req.region,
        role_arn=req.role_arn,
        org_scan=req.org_scan,
        provider=req.provider,
        credentials=provider_creds if provider_creds else None,
    )
    return acct


@app.get("/api/accounts/{account_id}")
async def api_get_account(account_id: str, _user: dict = Depends(require_auth)):
    acct = get_account(account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    # Mask secrets in response
    ak = acct.get("access_key", "")
    acct["access_key"] = (ak[:4] + "****" + ak[-4:]) if len(ak) > 8 else "****"
    acct["secret_key"] = "****"
    # Mask provider-specific credentials
    creds = acct.get("credentials", {})
    if creds:
        for secret_key in ("client_secret", "service_account_json"):
            if secret_key in creds and creds[secret_key]:
                creds[secret_key] = "****"
        acct["credentials"] = creds
    return acct


@app.patch("/api/accounts/{account_id}")
async def api_update_account(account_id: str, req: AccountUpdateRequest, _user: dict = Depends(require_auth)):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = update_account(account_id, **fields)
    if not ok:
        raise HTTPException(status_code=404, detail="Account not found or nothing to update")
    return {"status": "ok"}


@app.delete("/api/accounts/{account_id}")
async def api_delete_account(account_id: str, _user: dict = Depends(require_auth)):
    ok = delete_account(account_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.get("/api/accounts/{account_id}/scans")
async def api_list_scans(account_id: str, _user: dict = Depends(require_auth)):
    return list_scans(account_id)


@app.get("/api/accounts/{account_id}/latest-scan")
async def api_latest_scan(account_id: str, _user: dict = Depends(require_auth)):
    scan = get_latest_scan(account_id)
    if not scan:
        raise HTTPException(status_code=404, detail="No scans found")
    return scan


# ---------------------------------------------------------------------------
# Scan (updated with account + role_arn support)
# ---------------------------------------------------------------------------

@app.post("/api/scan")
async def start_scan(req: ScanRequest, _user: dict = Depends(require_auth)):
    # If scanning from a stored account, load credentials
    if req.stored_account_id:
        acct = get_account(req.stored_account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Stored account not found")
        req.provider = acct.get("provider", "aws")
        req.access_key = acct.get("access_key", "")
        req.secret_key = acct.get("secret_key", "")
        req.region = acct.get("region", req.region)
        req.role_arn = acct.get("role_arn") or req.role_arn
        req.org_scan = bool(acct.get("org_scan", req.org_scan))
        # Load provider-specific credentials
        creds = acct.get("credentials", {})
        if req.provider == "azure":
            req.azure_tenant_id = creds.get("tenant_id")
            req.azure_client_id = creds.get("client_id")
            req.azure_client_secret = creds.get("client_secret")
            req.azure_subscription_id = creds.get("subscription_id")
        elif req.provider == "gcp":
            req.gcp_project_id = creds.get("project_id")
            req.gcp_service_account_json = creds.get("service_account_json")

    scan_id = str(uuid.uuid4())[:8]
    _scans[scan_id] = {
        "status": "running",
        "progress": "Initializing...",
        "result": None,
        "error": None,
        "stored_account_id": req.stored_account_id,
    }
    thread = threading.Thread(target=_run_scan, args=(scan_id, req), daemon=True)
    thread.start()
    return {"scan_id": scan_id, "status": "running"}


@app.get("/api/scan/{scan_id}")
async def get_scan_status(scan_id: str, _user: dict = Depends(require_auth)):
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
async def get_scan_results(scan_id: str, _user: dict = Depends(require_auth)):
    scan = _scans.get(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan["status"] == "running":
        raise HTTPException(status_code=202, detail="Scan still running")
    if scan["status"] == "failed":
        raise HTTPException(status_code=500, detail=scan["error"])
    return scan["result"]


@app.get("/api/scan/{scan_id}/pdf")
async def download_scan_pdf(scan_id: str, _user: dict = Depends(require_auth)):
    """Generate and return a PDF report for a completed scan."""
    scan = _scans.get(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan["status"] == "running":
        raise HTTPException(status_code=202, detail="Scan still running")
    if scan["status"] == "failed":
        raise HTTPException(status_code=500, detail=scan["error"])

    result = scan["result"]
    try:
        from finxcloud.output.pdf_writer import PDFWriter
        writer = PDFWriter()
        pdf_bytes = writer.write_bytes(
            result.get("summary", {}),
            result.get("detailed", {}),
            result.get("roadmap", {}),
            tag_allocation=result.get("tag_allocation"),
        )
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="reportlab is not installed. Install with: pip install 'finxcloud[pdf]'",
        )

    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=finxcloud_report.pdf"},
    )


def _run_scan(scan_id: str, req: ScanRequest) -> None:
    """Execute the full scan pipeline in a background thread."""
    scan = _scans[scan_id]
    try:
        provider = req.provider

        if provider == "aws":
            _run_aws_scan(scan_id, req, scan)
        elif provider == "azure":
            _run_cloud_provider_scan(scan_id, req, scan, "azure")
        elif provider == "gcp":
            _run_cloud_provider_scan(scan_id, req, scan, "gcp")
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    except Exception as e:
        log.exception("Scan %s failed", scan_id)
        scan["status"] = "failed"
        scan["error"] = str(e)
        scan["progress"] = f"Failed: {e}"


def _run_cloud_provider_scan(scan_id: str, req: ScanRequest, scan: dict, provider_name: str) -> None:
    """Run a scan for Azure or GCP using the provider abstraction."""
    from finxcloud.providers.base import AzureCloudCredentials, GCPCloudCredentials, ProviderRegistry

    scan["progress"] = f"Setting up {provider_name.upper()} provider..."

    if provider_name == "azure":
        creds = AzureCloudCredentials(
            tenant_id=req.azure_tenant_id or "",
            client_id=req.azure_client_id or "",
            client_secret=req.azure_client_secret or "",
            subscription_id=req.azure_subscription_id or "",
            region=req.region,
        )
    else:
        creds = GCPCloudCredentials(
            project_id=req.gcp_project_id or "",
            service_account_json=req.gcp_service_account_json or "",
            region=req.region,
        )

    provider_cls = ProviderRegistry.get(provider_name)
    cloud_provider = provider_cls(creds)

    scan["progress"] = f"Validating {provider_name.upper()} credentials..."
    cloud_provider.validate_credentials()

    # Scan resources
    all_resources: list[dict] = []
    scanners = cloud_provider.get_scanners()
    for name, scanner in scanners:
        scan["progress"] = f"Scanning {name}..."
        try:
            resources = scanner.scan()
            for r in resources:
                r.setdefault("provider", provider_name)
            all_resources.extend(resources)
        except Exception:
            log.exception("Scanner %s failed", name)

    # Cost data
    all_cost_data: dict = {}
    scan["progress"] = f"Pulling {provider_name.upper()} cost data..."
    try:
        cost_analyzer = cloud_provider.get_cost_analyzer()
        all_cost_data[provider_name] = {
            "by_service": cost_analyzer.get_cost_by_service(req.days),
            "by_region": cost_analyzer.get_cost_by_region(req.days),
            "by_account": [],
            "daily_trend": cost_analyzer.get_daily_costs(req.days),
            "total_cost_30d": cost_analyzer.get_total_cost(req.days),
        }
    except Exception:
        log.exception("Cost data failed for %s", provider_name)
        all_cost_data[provider_name] = {
            "by_service": [], "by_region": [], "by_account": [],
            "daily_trend": [], "total_cost_30d": 0.0,
        }

    merged_cost_data = _merge_cost_data(all_cost_data)

    # Recommendations
    scan["progress"] = "Generating recommendations..."
    engine = RecommendationEngine(all_resources, merged_cost_data, None)
    recommendations = engine.generate_recommendations()

    # Reports
    scan["progress"] = "Building reports..."
    detailed_reporter = DetailedReporter(all_resources, merged_cost_data)
    detailed_report = detailed_reporter.generate()

    summary_reporter = SummaryReporter(detailed_report, recommendations)
    summary_report = summary_reporter.generate()

    roadmap_reporter = RoadmapReporter(recommendations)
    roadmap_report = roadmap_reporter.generate()

    result = {
        "summary": summary_report,
        "detailed": detailed_report,
        "roadmap": roadmap_report,
        "recommendations": recommendations,
        "resources": all_resources,
        "cost_data": merged_cost_data,
        "provider": provider_name,
    }

    stored_acct_id = scan.get("stored_account_id")
    if stored_acct_id:
        save_scan_result(stored_acct_id, result)

    scan["result"] = result
    scan["status"] = "done"
    scan["progress"] = "Scan complete"


def _run_aws_scan(scan_id: str, req: ScanRequest, scan: dict) -> None:
    """Execute the full AWS scan pipeline (original logic)."""
    # Parse regions
    region_list = [r.strip() for r in req.regions.split(",")] if req.regions else None

    # Authenticate
    scan["progress"] = "Validating AWS credentials..."
    creds = AWSCredentials(
        access_key_id=req.access_key,
        secret_access_key=req.secret_key,
        session_token=req.session_token,
        region=req.region,
        role_arn=req.role_arn,
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
                    r.setdefault("provider", "aws")
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

    # Cost Intelligence: Anomaly detection
    anomaly_data = {}
    scan["progress"] = "Running anomaly detection..."
    try:
        ce_primary = CostExplorerAnalyzer(session)
        detector = AnomalyDetector(ce_primary)
        anomaly_data = detector.detect(req.days)
    except Exception:
        log.exception("Anomaly detection failed")

    # Cost Intelligence: Budget tracking
    budget_data = {}
    scan["progress"] = "Analyzing budget and forecast..."
    try:
        tracker = BudgetTracker(ce_primary)
        account_id_for_budget = accounts_to_scan[0][0] if accounts_to_scan else "default"
        budget_data = tracker.analyze(account_id_for_budget, req.days)
    except Exception:
        log.exception("Budget analysis failed")

    # Cost Intelligence: Historical trends
    trends_data = {}
    scan["progress"] = "Analyzing historical cost trends..."
    try:
        trends_data = {
            "monthly_trend": ce_primary.get_monthly_trend(months=6),
            "monthly_by_service": ce_primary.get_monthly_cost_by_service(months=6),
        }
    except Exception:
        log.exception("Historical trend analysis failed")

    # Cost Intelligence: RI/Savings Plans coverage
    commitments_data = {}
    scan["progress"] = "Analyzing commitment coverage..."
    try:
        commitments_analyzer = CommitmentsAnalyzer(session)
        commitments_data = commitments_analyzer.analyze(req.days)
    except Exception:
        log.exception("Commitments analysis failed")

    # Tag-based cost allocation
    tag_allocation_data = None
    if req.allocation_tags:
        tag_list = [t.strip() for t in req.allocation_tags.split(",") if t.strip()]
        if tag_list:
            scan["progress"] = "Analyzing cost allocation by tags..."
            try:
                from finxcloud.analyzer.tags import TagCostAllocator
                tag_allocator = TagCostAllocator(session)
                tag_allocation_data = tag_allocator.get_cost_by_tags(tag_list, req.days)
            except Exception:
                log.exception("Tag allocation analysis failed")

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

    # Upload to S3 if configured
    s3_keys: list[str] = []
    if req.output_s3_bucket:
        scan["progress"] = "Uploading reports to S3..."
        s3w = S3Writer(session, req.output_s3_bucket, req.output_s3_prefix)
        s3_keys = s3w.write_all(detailed_report, summary_report, roadmap_report)

    result = {
        "summary": summary_report,
        "detailed": detailed_report,
        "roadmap": roadmap_report,
        "recommendations": recommendations,
        "resources": all_resources,
        "cost_data": merged_cost_data,
        "anomalies": anomaly_data,
        "budget": budget_data,
        "trends": trends_data,
        "commitments": commitments_data,
        "tag_allocation": tag_allocation_data,
        "s3_keys": s3_keys,
        "provider": "aws",
    }

    # Persist scan result if linked to a stored account
    stored_acct_id = scan.get("stored_account_id")
    if stored_acct_id:
        save_scan_result(stored_acct_id, result)

    scan["result"] = result
    scan["status"] = "done"
    scan["progress"] = "Scan complete"


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

@app.post("/api/email/send-report")
async def send_report_email(req: EmailReportRequest, _user: dict = Depends(require_auth)):
    """Send a scan report via email (SES or SMTP)."""
    # Build report HTML from the latest scan
    report_data = None

    if req.scan_id and req.scan_id in _scans:
        scan = _scans[req.scan_id]
        if scan["status"] == "done":
            report_data = scan["result"]

    if not report_data and req.account_id:
        latest = get_latest_scan(req.account_id)
        if latest and latest.get("result"):
            report_data = latest["result"]

    if not report_data:
        raise HTTPException(status_code=404, detail="No scan results found to send")

    subject = req.subject or "FinXCloud Cost Optimization Report"
    html_body = _build_report_email_html(report_data)

    if req.method == "ses":
        from finxcloud.email.sender import send_email_ses

        ses_session = None
        if req.aws_access_key and req.aws_secret_key:
            import boto3
            ses_session = boto3.Session(
                aws_access_key_id=req.aws_access_key,
                aws_secret_access_key=req.aws_secret_key,
                region_name=req.aws_region or "us-east-1",
            )
        from_addr = req.from_address or os.environ.get("FINXCLOUD_FROM_EMAIL", "noreply@finxcloud.io")
        ok = send_email_ses(
            to_addresses=req.to_addresses,
            subject=subject,
            html_body=html_body,
            from_address=from_addr,
            region=req.aws_region,
            session=ses_session,
        )
    else:
        from finxcloud.email.sender import EmailConfig, send_email

        config = EmailConfig()
        ok = send_email(config, req.to_addresses, subject, html_body)

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send email")
    return {"status": "ok", "message": f"Report sent to {', '.join(req.to_addresses)}"}


def _build_report_email_html(data: dict) -> str:
    """Build a simple HTML email from scan results."""
    summary = data.get("summary", {})
    ov = summary.get("overview", {})
    recs = summary.get("top_recommendations", [])[:10]

    rows = ""
    for r in recs:
        rows += (
            f"<tr><td>{r.get('category', '')}</td>"
            f"<td>{r.get('title', '')}</td>"
            f"<td>{r.get('effort_level', '')}</td>"
            f"<td>${r.get('estimated_monthly_savings', 0):.2f}</td></tr>"
        )

    return f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#333;">
    <h2 style="color:#1e3a5f;">FinXCloud Cost Optimization Report</h2>
    <table style="border-collapse:collapse;margin:1em 0;">
      <tr><td style="padding:4px 12px;font-weight:bold;">Total Resources</td><td>{ov.get('total_resources', 0)}</td></tr>
      <tr><td style="padding:4px 12px;font-weight:bold;">30-Day Cost</td><td style="color:#dc2626;">${ov.get('total_cost_30d', 0):.2f}</td></tr>
      <tr><td style="padding:4px 12px;font-weight:bold;">Potential Savings</td><td style="color:#16a34a;">${ov.get('total_potential_savings', 0):.2f}</td></tr>
      <tr><td style="padding:4px 12px;font-weight:bold;">Savings %</td><td>{ov.get('savings_percentage', 0)}%</td></tr>
    </table>
    <h3>Top Recommendations</h3>
    <table style="border-collapse:collapse;width:100%;">
      <tr style="background:#f3f4f6;">
        <th style="padding:6px 10px;text-align:left;">Category</th>
        <th style="padding:6px 10px;text-align:left;">Recommendation</th>
        <th style="padding:6px 10px;text-align:left;">Effort</th>
        <th style="padding:6px 10px;text-align:left;">Est. Savings/mo</th>
      </tr>
      {rows}
    </table>
    <p style="margin-top:2em;color:#6b7280;font-size:12px;">Generated by FinXCloud</p>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# S3 reports
# ---------------------------------------------------------------------------

class S3ReportRequest(BaseModel):
    access_key: str
    secret_key: str
    session_token: str | None = None
    region: str = "us-east-1"
    bucket: str
    prefix: str = ""


@app.post("/api/s3/reports")
async def list_s3_reports(req: S3ReportRequest, _user: dict = Depends(require_auth)):
    """List available reports in an S3 bucket."""
    creds = AWSCredentials(
        access_key_id=req.access_key,
        secret_access_key=req.secret_key,
        session_token=req.session_token,
        region=req.region,
    )
    session = create_session(creds)
    s3w = S3Writer(session, req.bucket, req.prefix)
    return {"keys": s3w.list_reports()}


@app.post("/api/s3/report")
async def get_s3_report(req: S3ReportRequest, filename: str = Query(...), _user: dict = Depends(require_auth)):
    """Read a specific JSON report from S3."""
    creds = AWSCredentials(
        access_key_id=req.access_key,
        secret_access_key=req.secret_key,
        session_token=req.session_token,
        region=req.region,
    )
    session = create_session(creds)
    s3w = S3Writer(session, req.bucket, req.prefix)
    return s3w.read_json(filename)


# ---------------------------------------------------------------------------
# Budget management
# ---------------------------------------------------------------------------

class BudgetRequest(BaseModel):
    account_id: str
    monthly_budget: float


@app.post("/api/budgets")
async def set_budget(req: BudgetRequest, _user: dict = Depends(require_auth)):
    """Set a monthly budget for an account."""
    from finxcloud.analyzer.budget import BudgetTracker, _DEFAULT_BUDGET_PATH
    tracker = BudgetTracker.__new__(BudgetTracker)
    tracker._budget_path = _DEFAULT_BUDGET_PATH
    tracker.set_budget(req.account_id, req.monthly_budget)
    return {"status": "ok", "account_id": req.account_id, "monthly_budget": req.monthly_budget}


@app.get("/api/budgets")
async def get_budgets(_user: dict = Depends(require_auth)):
    """Get all saved budgets."""
    from finxcloud.analyzer.budget import BudgetTracker, _DEFAULT_BUDGET_PATH
    tracker = BudgetTracker.__new__(BudgetTracker)
    tracker._budget_path = _DEFAULT_BUDGET_PATH
    return tracker.get_budgets()


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    instance_id: str
    region: str = "us-east-1"
    stop_time: str
    start_time: str
    days: list[str] = ["mon", "tue", "wed", "thu", "fri"]
    account_id: str | None = None
    estimated_monthly_savings: float = 0.0


class ScheduleUpdateRequest(BaseModel):
    stop_time: str | None = None
    start_time: str | None = None
    days: list[str] | None = None
    enabled: bool | None = None
    estimated_monthly_savings: float | None = None


@app.get("/api/schedules")
async def list_schedules(_user: dict = Depends(require_auth)):
    from finxcloud.scheduler.scheduler import ScheduleManager
    mgr = ScheduleManager()
    return mgr.list_schedules()


@app.post("/api/schedules")
async def create_schedule(req: ScheduleRequest, _user: dict = Depends(require_auth)):
    from finxcloud.scheduler.scheduler import ScheduleManager
    mgr = ScheduleManager()
    entry = mgr.add_schedule(
        instance_id=req.instance_id,
        region=req.region,
        stop_time=req.stop_time,
        start_time=req.start_time,
        days=req.days,
        account_id=req.account_id,
        estimated_monthly_savings=req.estimated_monthly_savings,
    )
    return entry


@app.patch("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, req: ScheduleUpdateRequest, _user: dict = Depends(require_auth)):
    from finxcloud.scheduler.scheduler import ScheduleManager
    mgr = ScheduleManager()
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = mgr.update_schedule(schedule_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return updated


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, _user: dict = Depends(require_auth)):
    from finxcloud.scheduler.scheduler import ScheduleManager
    mgr = ScheduleManager()
    if not mgr.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "ok"}


@app.post("/api/schedules/estimate-savings")
async def estimate_schedule_savings(req: ScheduleRequest, _user: dict = Depends(require_auth)):
    from finxcloud.scheduler.scheduler import ScheduleManager
    mgr = ScheduleManager()
    # Use a default hourly cost estimate for a generic instance
    hourly_cost = req.estimated_monthly_savings / (730) if req.estimated_monthly_savings > 0 else 0.10
    savings = mgr.estimate_savings(hourly_cost, req.stop_time, req.start_time, req.days)
    return {"estimated_monthly_savings": savings, "hourly_cost_used": hourly_cost}


# ---------------------------------------------------------------------------
# Webhooks / Notifications
# ---------------------------------------------------------------------------

class WebhookRequest(BaseModel):
    url: str
    name: str = ""
    type: str = "generic"
    events: list[str] = ["scan_complete", "anomaly_detected", "budget_threshold"]


class WebhookUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    type: str | None = None
    enabled: bool | None = None
    events: list[str] | None = None


class NotifyRequest(BaseModel):
    webhook_url: str | None = None
    event: str = "scan_complete"
    data: dict = {}


@app.get("/api/webhooks")
async def list_webhooks(_user: dict = Depends(require_auth)):
    from finxcloud.notifications.webhook import WebhookConfig
    cfg = WebhookConfig()
    return cfg.list_webhooks()


@app.post("/api/webhooks")
async def create_webhook(req: WebhookRequest, _user: dict = Depends(require_auth)):
    from finxcloud.notifications.webhook import WebhookConfig
    cfg = WebhookConfig()
    entry = cfg.add_webhook(url=req.url, name=req.name, webhook_type=req.type, events=req.events)
    return entry


@app.patch("/api/webhooks/{webhook_id}")
async def update_webhook(webhook_id: str, req: WebhookUpdateRequest, _user: dict = Depends(require_auth)):
    from finxcloud.notifications.webhook import WebhookConfig
    cfg = WebhookConfig()
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = cfg.update_webhook(webhook_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return updated


@app.delete("/api/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, _user: dict = Depends(require_auth)):
    from finxcloud.notifications.webhook import WebhookConfig
    cfg = WebhookConfig()
    if not cfg.delete_webhook(webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"status": "ok"}


@app.post("/api/webhooks/test")
async def test_webhook(req: NotifyRequest, _user: dict = Depends(require_auth)):
    from finxcloud.notifications.webhook import NotificationSender
    sender = NotificationSender()
    if req.webhook_url:
        result = sender.send_to_url(req.webhook_url, req.event, req.data or {"message": "Test notification from FinXCloud"})
    else:
        results = sender.notify(req.event, req.data or {"message": "Test notification from FinXCloud"})
        if not results:
            raise HTTPException(status_code=404, detail="No webhooks configured for this event")
        result = results[0]
    if result["status"] != "ok":
        raise HTTPException(status_code=502, detail=result.get("error", "Webhook send failed"))
    return result


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------

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
