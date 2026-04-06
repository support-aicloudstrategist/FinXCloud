"""FinXCloud CLI — Multi-Cloud Cost Optimization Tool."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from finxcloud.auth.credentials import AWSCredentials, create_session, validate_credentials
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
from finxcloud.output.json_writer import JSONWriter
from finxcloud.output.html_writer import HTMLWriter
from finxcloud.output.s3_writer import S3Writer
from finxcloud.providers.base import (
    AWSCloudCredentials,
    AzureCloudCredentials,
    GCPCloudCredentials,
    ProviderRegistry,
)
# Register all providers
import finxcloud.providers.aws  # noqa: F401
import finxcloud.providers.azure  # noqa: F401
import finxcloud.providers.gcp  # noqa: F401

console = Console()
log = logging.getLogger("finxcloud")


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def main(verbose: bool) -> None:
    """FinXCloud — Multi-Cloud Cost Optimization Tool."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Multi-cloud scan command
# ---------------------------------------------------------------------------

@main.command("scan-cloud")
@click.option("--provider", type=click.Choice(["aws", "azure", "gcp", "all"]), default="aws",
              help="Cloud provider to scan (aws, azure, gcp, or all).")
# AWS options
@click.option("--access-key", envvar="AWS_ACCESS_KEY_ID", default=None, help="AWS Access Key ID.")
@click.option("--secret-key", envvar="AWS_SECRET_ACCESS_KEY", default=None, help="AWS Secret Access Key.")
@click.option("--session-token", envvar="AWS_SESSION_TOKEN", default=None, help="AWS Session Token.")
@click.option("--profile", default=None, help="AWS CLI profile name.")
# Azure options
@click.option("--azure-tenant-id", envvar="AZURE_TENANT_ID", default=None, help="Azure Tenant ID.")
@click.option("--azure-client-id", envvar="AZURE_CLIENT_ID", default=None, help="Azure Client ID.")
@click.option("--azure-client-secret", envvar="AZURE_CLIENT_SECRET", default=None, help="Azure Client Secret.")
@click.option("--azure-subscription-id", envvar="AZURE_SUBSCRIPTION_ID", default=None, help="Azure Subscription ID.")
@click.option("--azure-use-cli", is_flag=True, help="Use Azure CLI credentials.")
# GCP options
@click.option("--gcp-project-id", envvar="GCP_PROJECT_ID", default=None, help="GCP Project ID.")
@click.option("--gcp-service-account-json", envvar="GCP_SERVICE_ACCOUNT_JSON", default=None,
              help="GCP Service Account JSON key (string or file path).")
@click.option("--gcp-use-cli", is_flag=True, help="Use gcloud CLI credentials.")
# Common options
@click.option("--region", default=None, help="Default region (provider-specific).")
@click.option("--days", default=30, type=int, help="Cost analysis lookback period in days.")
@click.option("--output-dir", "-o", default="reports", help="Output directory for reports.")
@click.option("--output-pdf", is_flag=True, help="Generate a PDF executive summary report.")
def scan_cloud(
    provider: str,
    access_key: str | None,
    secret_key: str | None,
    session_token: str | None,
    profile: str | None,
    azure_tenant_id: str | None,
    azure_client_id: str | None,
    azure_client_secret: str | None,
    azure_subscription_id: str | None,
    azure_use_cli: bool,
    gcp_project_id: str | None,
    gcp_service_account_json: str | None,
    gcp_use_cli: bool,
    region: str | None,
    days: int,
    output_dir: str,
    output_pdf: bool,
) -> None:
    """Run a multi-cloud cost optimization scan (AWS, Azure, GCP)."""
    console.print("\n[bold blue]FinXCloud[/bold blue] — Multi-Cloud Cost Optimization Tool\n")

    providers_to_scan = []

    if provider in ("aws", "all"):
        if access_key and secret_key:
            aws_creds = AWSCloudCredentials(
                access_key_id=access_key,
                secret_access_key=secret_key,
                session_token=session_token,
                region=region or "us-east-1",
                profile=profile,
            )
            aws_provider_cls = ProviderRegistry.get("aws")
            providers_to_scan.append(aws_provider_cls(aws_creds))
        elif provider == "aws":
            console.print("[red]AWS credentials required (--access-key, --secret-key).[/red]")
            sys.exit(1)

    if provider in ("azure", "all"):
        if azure_subscription_id and (azure_use_cli or (azure_client_id and azure_client_secret)):
            azure_creds = AzureCloudCredentials(
                tenant_id=azure_tenant_id or "",
                client_id=azure_client_id or "",
                client_secret=azure_client_secret or "",
                subscription_id=azure_subscription_id,
                region=region or "eastus",
                use_cli=azure_use_cli,
            )
            azure_provider_cls = ProviderRegistry.get("azure")
            providers_to_scan.append(azure_provider_cls(azure_creds))
        elif provider == "azure":
            console.print("[red]Azure credentials required (--azure-subscription-id + --azure-use-cli or Service Principal).[/red]")
            sys.exit(1)

    if provider in ("gcp", "all"):
        if gcp_project_id and (gcp_use_cli or gcp_service_account_json):
            sa_json = gcp_service_account_json or ""
            if sa_json and Path(sa_json).is_file():
                sa_json = Path(sa_json).read_text()
            gcp_creds = GCPCloudCredentials(
                project_id=gcp_project_id,
                service_account_json=sa_json,
                region=region or "us-central1",
                use_cli=gcp_use_cli,
            )
            gcp_provider_cls = ProviderRegistry.get("gcp")
            providers_to_scan.append(gcp_provider_cls(gcp_creds))
        elif provider == "gcp":
            console.print("[red]GCP credentials required (--gcp-project-id + --gcp-use-cli or --gcp-service-account-json).[/red]")
            sys.exit(1)

    if not providers_to_scan:
        console.print("[red]No providers configured. Provide credentials for at least one cloud provider.[/red]")
        sys.exit(1)

    all_resources: list[dict] = []
    all_cost_data: dict = {}

    for cloud_provider in providers_to_scan:
        console.print(f"\n[bold]Scanning {cloud_provider.name.upper()} resources...[/bold]")

        # Validate credentials
        with console.status(f"[bold green]Validating {cloud_provider.name.upper()} credentials..."):
            try:
                identity = cloud_provider.validate_credentials()
                console.print(f"  [green]Authenticated: {identity}[/green]")
            except Exception as e:
                console.print(f"  [red]Authentication failed: {e}[/red]")
                continue

        # Run scanners
        scanners = cloud_provider.get_scanners()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for name, scanner in scanners:
                task = progress.add_task(f"Scanning {name}...", total=None)
                try:
                    resources = scanner.scan()
                    for r in resources:
                        r.setdefault("provider", cloud_provider.name)
                    all_resources.extend(resources)
                    progress.update(task, description=f"[green]{name}: {len(resources)} resources")
                except Exception as e:
                    progress.update(task, description=f"[red]{name}: {e}")
                    log.error("Scanner %s failed: %s", name, e)
                progress.update(task, completed=True)

        # Cost data
        with console.status(f"[bold green]Pulling {cloud_provider.name.upper()} cost data..."):
            try:
                cost_analyzer = cloud_provider.get_cost_analyzer()
                provider_cost = {
                    "by_service": cost_analyzer.get_cost_by_service(days),
                    "by_region": cost_analyzer.get_cost_by_region(days),
                    "by_account": [],
                    "daily_trend": cost_analyzer.get_daily_costs(days),
                    "total_cost_30d": cost_analyzer.get_total_cost(days),
                }
                all_cost_data[cloud_provider.name] = provider_cost
                console.print(f"  Total cost ({days}d): [bold]${provider_cost['total_cost_30d']:.2f}[/bold]")
            except Exception as e:
                console.print(f"  [yellow]Cost data unavailable: {e}[/yellow]")
                all_cost_data[cloud_provider.name] = {
                    "by_service": [], "by_region": [], "by_account": [],
                    "daily_trend": [], "total_cost_30d": 0.0,
                }

    # Merge cost data
    merged_cost_data = _merge_cost_data(all_cost_data)

    # Recommendations (no utilization for non-AWS providers yet)
    with console.status("[bold green]Generating recommendations..."):
        engine = RecommendationEngine(all_resources, merged_cost_data, None)
        recommendations = engine.generate_recommendations()
        console.print(f"  Generated [bold]{len(recommendations)}[/bold] recommendations")

    # Reports
    with console.status("[bold green]Building reports..."):
        detailed_reporter = DetailedReporter(all_resources, merged_cost_data)
        detailed_report = detailed_reporter.generate()

        summary_reporter = SummaryReporter(detailed_report, recommendations)
        summary_report = summary_reporter.generate()

        roadmap_reporter = RoadmapReporter(recommendations)
        roadmap_report = roadmap_reporter.generate()

    # Write output
    with console.status("[bold green]Writing reports..."):
        json_writer = JSONWriter(output_dir)
        json_files = json_writer.write_all(detailed_report, summary_report, roadmap_report)

        html_writer = HTMLWriter(output_dir)
        html_file = html_writer.write(summary_report, detailed_report, roadmap_report)

    # PDF export
    pdf_file = None
    if output_pdf:
        with console.status("[bold green]Generating PDF report..."):
            try:
                from finxcloud.output.pdf_writer import PDFWriter
                pdf_writer = PDFWriter(output_dir)
                pdf_file = pdf_writer.write(summary_report, detailed_report, roadmap_report)
            except ImportError:
                console.print("  [red]reportlab is required for PDF export.[/red]")
            except Exception as e:
                console.print(f"  [yellow]PDF generation failed: {e}[/yellow]")

    # Print summary
    console.print("\n" + "=" * 60)
    console.print("[bold blue]FinXCloud Multi-Cloud Scan Complete[/bold blue]")
    console.print("=" * 60)
    _print_summary_table(summary_report)
    console.print(f"\n[bold]Reports written to:[/bold]")
    for f in json_files:
        console.print(f"  {f}")
    console.print(f"  {html_file}")
    if pdf_file:
        console.print(f"  {pdf_file}")
    console.print()


# ---------------------------------------------------------------------------
# Original AWS scan command (backward compatible)
# ---------------------------------------------------------------------------

@main.command()
@click.option("--provider", type=click.Choice(["aws", "azure", "gcp"]), default="aws",
              help="Cloud provider to scan.")
@click.option("--access-key", envvar="AWS_ACCESS_KEY_ID", required=True, help="AWS Access Key ID.")
@click.option("--secret-key", envvar="AWS_SECRET_ACCESS_KEY", required=True, help="AWS Secret Access Key.")
@click.option("--session-token", envvar="AWS_SESSION_TOKEN", default=None, help="AWS Session Token (optional).")
@click.option("--region", default="us-east-1", help="Default AWS region.")
@click.option("--profile", default=None, help="AWS CLI profile name (overrides key-based auth).")
@click.option("--org/--no-org", default=False, help="Scan all accounts in AWS Organization.")
@click.option("--org-role", default="OrganizationAccountAccessRole", help="Role to assume in member accounts.")
@click.option("--days", default=30, type=int, help="Cost analysis lookback period in days.")
@click.option("--output-dir", "-o", default="reports", help="Output directory for reports.")
@click.option("--regions", default=None, help="Comma-separated list of regions to scan (default: all).")
@click.option("--output-s3-bucket", default=None, help="S3 bucket to upload reports to (in addition to local disk).")
@click.option("--output-s3-prefix", default="", help="S3 key prefix for uploaded reports.")
@click.option("--skip-utilization", is_flag=True, help="Skip CloudWatch utilization checks (faster).")
@click.option("--output-pdf", is_flag=True, help="Generate a PDF executive summary report.")
@click.option("--allocation-tags", default=None, help="Comma-separated AWS cost-allocation tags (e.g. Team,Project,Environment).")
def scan(
    provider: str,
    access_key: str,
    secret_key: str,
    session_token: str | None,
    region: str,
    profile: str | None,
    org: bool,
    org_role: str,
    days: int,
    output_s3_bucket: str | None,
    output_s3_prefix: str,
    output_dir: str,
    regions: str | None,
    skip_utilization: bool,
    output_pdf: bool,
    allocation_tags: str | None,
) -> None:
    """Run a full AWS cost optimization scan."""
    console.print("\n[bold blue]FinXCloud[/bold blue] — AWS Cost Optimization Tool\n")

    # Parse regions
    region_list = [r.strip() for r in regions.split(",")] if regions else None

    # Create credentials and session
    creds = AWSCredentials(
        access_key_id=access_key,
        secret_access_key=secret_key,
        session_token=session_token,
        region=region,
        profile=profile,
    )
    session = create_session(creds)

    # Validate credentials
    with console.status("[bold green]Validating AWS credentials..."):
        try:
            identity = validate_credentials(session)
            console.print(f"  ✓ Authenticated as [bold]{identity['Arn']}[/bold]")
        except Exception as e:
            console.print(f"  [red]✗ Authentication failed: {e}[/red]")
            sys.exit(1)

    # Determine accounts to scan
    accounts_to_scan: list[tuple[str, boto3.Session]] = []
    if org:
        with console.status("[bold green]Discovering Organization accounts..."):
            if is_organizations_account(session):
                members = list_member_accounts(session)
                console.print(f"  ✓ Found [bold]{len(members)}[/bold] member accounts")
                for member in members:
                    try:
                        member_session = assume_role_session(
                            session, member["id"], org_role, region
                        )
                        accounts_to_scan.append((member["id"], member_session))
                    except Exception as e:
                        console.print(f"  [yellow]⚠ Could not assume role in {member['id']}: {e}[/yellow]")
            else:
                console.print("  [yellow]⚠ Not an Organizations account, scanning current account only[/yellow]")

    if not accounts_to_scan:
        account_id = identity.get("Account", "unknown")
        accounts_to_scan.append((account_id, session))

    # Run scans
    all_resources: list[dict] = []
    all_cost_data: dict = {}

    for account_id, acct_session in accounts_to_scan:
        console.print(f"\n[bold]Scanning account {account_id}[/bold]")

        # Resource scanning
        scanners = [
            ("EC2/EBS/Snapshots", EC2Scanner(acct_session, region_list)),
            ("RDS", RDSScanner(acct_session, region_list)),
            ("S3", S3Scanner(acct_session, region_list)),
            ("Lambda", LambdaScanner(acct_session, region_list)),
            ("Networking", NetworkingScanner(acct_session, region_list)),
            ("OpenSearch", OpenSearchScanner(acct_session, region_list)),
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for name, scanner in scanners:
                task = progress.add_task(f"Scanning {name}...", total=None)
                try:
                    resources = scanner.scan()
                    for r in resources:
                        r["account_id"] = account_id
                    all_resources.extend(resources)
                    progress.update(task, description=f"[green]✓ {name}: {len(resources)} resources")
                except Exception as e:
                    progress.update(task, description=f"[red]✗ {name}: {e}")
                    log.error("Scanner %s failed for account %s: %s", name, account_id, e)
                progress.update(task, completed=True)

        # Cost Explorer
        with console.status(f"[bold green]Pulling Cost Explorer data for {account_id}..."):
            try:
                ce = CostExplorerAnalyzer(acct_session)
                all_cost_data[account_id] = {
                    "by_service": ce.get_cost_by_service(days),
                    "by_region": ce.get_cost_by_region(days),
                    "by_account": ce.get_cost_by_account(days),
                    "daily_trend": ce.get_daily_costs(days),
                    "total_cost_30d": ce.get_total_cost(days),
                }
                console.print(f"  ✓ Total cost ({days}d): [bold]${all_cost_data[account_id]['total_cost_30d']:.2f}[/bold]")
            except Exception as e:
                console.print(f"  [yellow]⚠ Cost Explorer unavailable: {e}[/yellow]")
                all_cost_data[account_id] = {
                    "by_service": [], "by_region": [], "by_account": [],
                    "daily_trend": [], "total_cost_30d": 0.0,
                }

    # Merge cost data for reporting
    merged_cost_data = _merge_cost_data(all_cost_data)

    # Cost Intelligence features
    console.print("\n[bold]Running cost intelligence analysis...[/bold]")
    ce_primary = CostExplorerAnalyzer(session)

    with console.status("[bold green]Detecting cost anomalies..."):
        try:
            detector = AnomalyDetector(ce_primary)
            anomaly_data = detector.detect(days)
            anomaly_count = len(anomaly_data.get("anomalies", []))
            if anomaly_count:
                console.print(f"  [yellow]! {anomaly_count} cost anomalies detected[/yellow]")
            else:
                console.print(f"  [green]No cost anomalies detected[/green]")
        except Exception as e:
            console.print(f"  [yellow]Anomaly detection unavailable: {e}[/yellow]")

    with console.status("[bold green]Analyzing budget and forecast..."):
        try:
            budget_account = accounts_to_scan[0][0] if accounts_to_scan else "default"
            tracker = BudgetTracker(ce_primary)
            budget_data = tracker.analyze(budget_account, days)
            if budget_data.get("budget", 0) > 0:
                status = "[green]on track[/green]" if budget_data["on_track"] else "[red]over budget[/red]"
                console.print(f"  Budget: ${budget_data['budget']:.2f}/mo | MTD: ${budget_data['actual_mtd']:.2f} | Forecast: ${budget_data['forecast_eom']:.2f} — {status}")
            else:
                console.print(f"  No budget set. Forecast EOM: [bold]${budget_data['forecast_eom']:.2f}[/bold]")
        except Exception as e:
            console.print(f"  [yellow]Budget analysis unavailable: {e}[/yellow]")

    with console.status("[bold green]Analyzing historical trends..."):
        try:
            monthly_trend = ce_primary.get_monthly_trend(months=6)
            if monthly_trend:
                latest = monthly_trend[-1]
                console.print(f"  Latest month ({latest['month']}): ${latest['amount']:.2f} ({latest['change_pct']:+.1f}% MoM)")
        except Exception as e:
            console.print(f"  [yellow]Trend analysis unavailable: {e}[/yellow]")

    with console.status("[bold green]Analyzing commitment coverage..."):
        try:
            commitments_analyzer = CommitmentsAnalyzer(session)
            commitments_data = commitments_analyzer.analyze(days)
            console.print(f"  Commitment coverage: [bold]{commitments_data['total_committed_pct']:.1f}%[/bold] | On-demand: {commitments_data['total_on_demand_pct']:.1f}%")
        except Exception as e:
            console.print(f"  [yellow]Commitment analysis unavailable: {e}[/yellow]")

    # Tag-based cost allocation
    tag_allocation_data = None
    if allocation_tags:
        tag_list = [t.strip() for t in allocation_tags.split(",") if t.strip()]
        if tag_list:
            with console.status("[bold green]Analyzing cost allocation by tags..."):
                try:
                    from finxcloud.analyzer.tags import TagCostAllocator
                    tag_allocator = TagCostAllocator(session)
                    tag_allocation_data = tag_allocator.get_cost_by_tags(tag_list, days)
                    for tg in tag_allocation_data.get("by_tag", []):
                        tag_key = tg["tag_key"]
                        num_vals = len(tg["values"])
                        console.print(f"  Tag [bold]{tag_key}[/bold]: {num_vals} values, total ${tg['total']:.2f}")
                except Exception as e:
                    console.print(f"  [yellow]Tag allocation unavailable: {e}[/yellow]")

    # Utilization analysis
    utilization_analyzer = None
    if not skip_utilization:
        console.print("\n[bold]Collecting utilization metrics...[/bold]")
        utilization_analyzer = UtilizationAnalyzer(session)

    # Recommendations
    with console.status("[bold green]Generating recommendations..."):
        engine = RecommendationEngine(all_resources, merged_cost_data, utilization_analyzer)
        recommendations = engine.generate_recommendations()
        console.print(f"  ✓ Generated [bold]{len(recommendations)}[/bold] recommendations")

    # Reports
    with console.status("[bold green]Building reports..."):
        detailed_reporter = DetailedReporter(all_resources, merged_cost_data)
        detailed_report = detailed_reporter.generate()

        summary_reporter = SummaryReporter(detailed_report, recommendations)
        summary_report = summary_reporter.generate()

        roadmap_reporter = RoadmapReporter(recommendations)
        roadmap_report = roadmap_reporter.generate()

    # Write output
    with console.status("[bold green]Writing reports..."):
        json_writer = JSONWriter(output_dir)
        json_files = json_writer.write_all(detailed_report, summary_report, roadmap_report)

        html_writer = HTMLWriter(output_dir)
        html_file = html_writer.write(summary_report, detailed_report, roadmap_report)

    # PDF export
    pdf_file = None
    if output_pdf:
        with console.status("[bold green]Generating PDF report..."):
            try:
                from finxcloud.output.pdf_writer import PDFWriter
                pdf_writer = PDFWriter(output_dir)
                pdf_file = pdf_writer.write(
                    summary_report, detailed_report, roadmap_report,
                    tag_allocation=tag_allocation_data,
                )
            except ImportError:
                console.print("  [red]reportlab is required for PDF export. Install with: pip install 'finxcloud[pdf]'[/red]")
            except Exception as e:
                console.print(f"  [yellow]PDF generation failed: {e}[/yellow]")

    # Upload to S3 if configured
    s3_keys: list[str] = []
    if output_s3_bucket:
        with console.status("[bold green]Uploading reports to S3..."):
            s3w = S3Writer(session, output_s3_bucket, output_s3_prefix)
            # Read the rendered HTML from disk to upload
            with open(html_file, "r", encoding="utf-8") as fh:
                html_content = fh.read()
            s3_keys = s3w.write_all(detailed_report, summary_report, roadmap_report, html_content)
            console.print(f"  ✓ Uploaded [bold]{len(s3_keys)}[/bold] reports to s3://{output_s3_bucket}")

    # Print summary
    console.print("\n" + "=" * 60)
    console.print("[bold blue]FinXCloud Scan Complete[/bold blue]")
    console.print("=" * 60)

    _print_summary_table(summary_report)

    console.print(f"\n[bold]Reports written to:[/bold]")
    for f in json_files:
        console.print(f"  📄 {f}")
    console.print(f"  🌐 {html_file}")
    if pdf_file:
        console.print(f"  📊 {pdf_file}")
    if s3_keys:
        console.print(f"\n[bold]Reports uploaded to S3:[/bold]")
        for key in s3_keys:
            console.print(f"  ☁️  s3://{output_s3_bucket}/{key}")
    console.print()


def _merge_cost_data(cost_data_by_account: dict) -> dict:
    """Merge cost data from multiple accounts into a single dict."""
    if len(cost_data_by_account) == 1:
        return next(iter(cost_data_by_account.values()))

    merged = {
        "by_service": [],
        "by_region": [],
        "by_account": [],
        "daily_trend": [],
        "total_cost_30d": 0.0,
    }
    service_totals: dict[str, float] = {}
    region_totals: dict[str, float] = {}
    daily_totals: dict[str, float] = {}

    for account_id, data in cost_data_by_account.items():
        merged["total_cost_30d"] += data.get("total_cost_30d", 0.0)
        merged["by_account"].append({
            "account": account_id,
            "amount": data.get("total_cost_30d", 0.0),
            "unit": "USD",
            "currency": "USD",
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
        {"date": k, "amount": v}
        for k, v in sorted(daily_totals.items())
    ]
    return merged


def _print_summary_table(summary: dict) -> None:
    """Print a rich summary table to the console."""
    overview = summary.get("overview", {})

    table = Table(title="Executive Summary", show_header=False, border_style="blue")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total Resources", str(overview.get("total_resources", 0)))
    table.add_row("Total Cost (30d)", f"${overview.get('total_cost_30d', 0):.2f}")
    table.add_row("Potential Savings", f"[green]${overview.get('total_potential_savings', 0):.2f}[/green]")
    savings_pct = overview.get("savings_percentage", 0)
    table.add_row("Savings Opportunity", f"[green]{savings_pct:.1f}%[/green]")
    table.add_row("Quick Wins", str(summary.get("quick_wins_count", 0)))

    console.print(table)

    # Top recommendations
    top_recs = summary.get("top_recommendations", [])
    if top_recs:
        rec_table = Table(title="Top Recommendations", border_style="green")
        rec_table.add_column("#", style="dim", width=3)
        rec_table.add_column("Category")
        rec_table.add_column("Title")
        rec_table.add_column("Est. Savings/mo", justify="right", style="green")
        rec_table.add_column("Effort")

        for i, rec in enumerate(top_recs[:10], 1):
            rec_table.add_row(
                str(i),
                rec.get("category", ""),
                rec.get("title", ""),
                f"${rec.get('estimated_monthly_savings', 0):.2f}",
                rec.get("effort_level", ""),
            )

        console.print(rec_table)


# Need to import boto3 for type hint in accounts_to_scan
import boto3  # noqa: E402


@main.command("export-pdf")
@click.option("--report-dir", default="reports", help="Directory containing existing JSON reports.")
@click.option("--output-dir", "-o", default=None, help="Output directory for PDF (defaults to report-dir).")
def export_pdf(report_dir: str, output_dir: str | None) -> None:
    """Generate a PDF executive summary from existing JSON reports."""
    report_path = Path(report_dir)
    out_dir = output_dir or report_dir

    # Load reports
    reports = {}
    for name in ("summary_report", "detailed_report", "roadmap_report"):
        fpath = report_path / f"{name}.json"
        if fpath.exists():
            reports[name.replace("_report", "")] = json.loads(fpath.read_text())
            console.print(f"  Loaded {fpath}")
        else:
            console.print(f"  [yellow]{fpath} not found[/yellow]")

    if "summary" not in reports or "detailed" not in reports:
        console.print("[red]Missing required reports (summary_report.json, detailed_report.json).[/red]")
        sys.exit(1)

    try:
        from finxcloud.output.pdf_writer import PDFWriter
        pdf_writer = PDFWriter(out_dir)
        pdf_file = pdf_writer.write(
            reports["summary"],
            reports["detailed"],
            reports.get("roadmap", {"phases": []}),
        )
        console.print(f"\n  [green]PDF report generated: {pdf_file}[/green]")
    except ImportError:
        console.print("[red]reportlab is required. Install with: pip install 'finxcloud[pdf]'[/red]")
        sys.exit(1)


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind the web server to.")
@click.option("--port", "-p", default=8000, type=int, help="Port for the web server.")
@click.option("--reload", "do_reload", is_flag=True, help="Enable auto-reload for development.")
def web(host: str, port: int, do_reload: bool) -> None:
    """Launch the FinXCloud web dashboard."""
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]uvicorn is not installed. "
            "Install web dependencies with: pip install 'finxcloud[web]'[/red]"
        )
        sys.exit(1)

    console.print(f"\n[bold blue]FinXCloud Web Dashboard[/bold blue]")
    console.print(f"  Starting at [bold]http://{host}:{port}[/bold]\n")
    uvicorn.run("finxcloud.web.app:app", host=host, port=port, reload=do_reload)


@main.command()
@click.option("--access-key", envvar="AWS_ACCESS_KEY_ID", required=True, help="AWS Access Key ID.")
@click.option("--secret-key", envvar="AWS_SECRET_ACCESS_KEY", required=True, help="AWS Secret Access Key.")
@click.option("--session-token", envvar="AWS_SESSION_TOKEN", default=None, help="AWS Session Token.")
@click.option("--region", default="us-east-1", help="AWS region.")
@click.option("--bucket", required=True, help="S3 bucket name for hosting the dashboard.")
@click.option("--prefix", default="", help="S3 key prefix (subfolder).")
@click.option("--report-dir", default="reports", help="Local directory with existing JSON reports to embed.")
@click.option("--days", default=30, type=int, help="Cost analysis lookback period (if running a fresh scan).")
@click.option("--skip-utilization", is_flag=True, help="Skip CloudWatch utilization checks.")
@click.option("--from-reports", is_flag=True, help="Use existing local reports instead of running a new scan.")
@click.option("--deploy-password", default=None, help="Password to protect the static dashboard (client-side gate).")
def deploy(
    access_key: str,
    secret_key: str,
    session_token: str | None,
    region: str,
    bucket: str,
    prefix: str,
    report_dir: str,
    days: int,
    skip_utilization: bool,
    from_reports: bool,
    deploy_password: str | None,
) -> None:
    """Deploy the FinXCloud dashboard to S3 with a public URL.

    Either runs a fresh scan or uses existing reports from --report-dir.
    """
    from finxcloud.web.deploy import deploy_to_s3

    creds = AWSCredentials(
        access_key_id=access_key,
        secret_access_key=secret_key,
        session_token=session_token,
        region=region,
    )
    session = create_session(creds)

    console.print("\n[bold blue]FinXCloud Deploy[/bold blue]\n")

    if from_reports:
        # Load existing reports
        report_path = Path(report_dir)
        report_data = {}
        for name in ("summary_report", "detailed_report", "roadmap_report"):
            fpath = report_path / f"{name}.json"
            if fpath.exists():
                report_data[name.replace("_report", "")] = json.loads(fpath.read_text())
                console.print(f"  ✓ Loaded {fpath}")
            else:
                console.print(f"  [yellow]⚠ {fpath} not found[/yellow]")
    else:
        # Run a fresh scan
        with console.status("[bold green]Validating credentials..."):
            identity = validate_credentials(session)
            console.print(f"  ✓ Authenticated as [bold]{identity['Arn']}[/bold]")

        account_id = identity.get("Account", "unknown")
        all_resources: list[dict] = []

        scanners = [
            ("EC2/EBS/Snapshots", EC2Scanner(session)),
            ("RDS", RDSScanner(session)),
            ("S3", S3Scanner(session)),
            ("Lambda", LambdaScanner(session)),
            ("Networking", NetworkingScanner(session)),
            ("OpenSearch", OpenSearchScanner(session)),
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for name, scanner in scanners:
                task = progress.add_task(f"Scanning {name}...", total=None)
                try:
                    resources = scanner.scan()
                    for r in resources:
                        r["account_id"] = account_id
                    all_resources.extend(resources)
                    progress.update(task, description=f"[green]✓ {name}: {len(resources)} resources")
                except Exception as e:
                    progress.update(task, description=f"[red]✗ {name}: {e}")
                progress.update(task, completed=True)

        with console.status("[bold green]Pulling Cost Explorer data..."):
            try:
                ce = CostExplorerAnalyzer(session)
                cost_data = {
                    "by_service": ce.get_cost_by_service(days),
                    "by_region": ce.get_cost_by_region(days),
                    "by_account": ce.get_cost_by_account(days),
                    "daily_trend": ce.get_daily_costs(days),
                    "total_cost_30d": ce.get_total_cost(days),
                }
            except Exception:
                cost_data = {
                    "by_service": [], "by_region": [], "by_account": [],
                    "daily_trend": [], "total_cost_30d": 0.0,
                }

        utilization_analyzer = None
        if not skip_utilization:
            utilization_analyzer = UtilizationAnalyzer(session)

        with console.status("[bold green]Generating reports..."):
            engine = RecommendationEngine(all_resources, cost_data, utilization_analyzer)
            recommendations = engine.generate_recommendations()

            detailed_reporter = DetailedReporter(all_resources, cost_data)
            detailed_report = detailed_reporter.generate()

            summary_reporter = SummaryReporter(detailed_report, recommendations)
            summary_report = summary_reporter.generate()

            roadmap_reporter = RoadmapReporter(recommendations)
            roadmap_report = roadmap_reporter.generate()

        report_data = {
            "summary": summary_report,
            "detailed": detailed_report,
            "roadmap": roadmap_report,
            "recommendations": recommendations,
        }

    # Deploy to S3
    with console.status(f"[bold green]Deploying to S3 bucket '{bucket}'..."):
        url = deploy_to_s3(session, bucket, report_data, prefix, deploy_password=deploy_password)

    console.print(f"\n  ✓ Dashboard deployed successfully!")
    console.print(f"\n  [bold green]🌐 Public URL: {url}[/bold green]\n")


@main.command("send-report")
@click.option("--to", "to_email", required=True, help="Recipient email address(es), comma-separated.")
@click.option("--subject", default=None, help="Email subject (auto-generated if omitted).")
@click.option("--report-file", required=True, help="Path to an HTML file to send as the email body.")
@click.option("--from-email", envvar="FINXCLOUD_FROM_EMAIL", required=True, help="Sender email address.")
@click.option("--via", "send_method", type=click.Choice(["ses", "smtp"]), default="ses",
              help="Send method: 'ses' (AWS SES API, default) or 'smtp'.")
@click.option("--region", default="us-east-1", help="AWS region for SES (only used with --via ses).")
@click.option("--access-key", envvar="AWS_ACCESS_KEY_ID", default=None, help="AWS Access Key (for SES).")
@click.option("--secret-key", envvar="AWS_SECRET_ACCESS_KEY", default=None, help="AWS Secret Key (for SES).")
@click.option("--smtp-host", envvar="FINXCLOUD_SMTP_HOST", default=None, help="SMTP server hostname.")
@click.option("--smtp-port", envvar="FINXCLOUD_SMTP_PORT", default=587, type=int, help="SMTP server port.")
@click.option("--smtp-user", envvar="FINXCLOUD_SMTP_USER", default=None, help="SMTP username.")
@click.option("--smtp-password", envvar="FINXCLOUD_SMTP_PASSWORD", default=None, help="SMTP password.")
def send_report(
    to_email: str,
    subject: str | None,
    report_file: str,
    from_email: str,
    send_method: str,
    region: str,
    access_key: str | None,
    secret_key: str | None,
    smtp_host: str | None,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
) -> None:
    """Send a report email via AWS SES API or SMTP."""
    html_body = Path(report_file).read_text(encoding="utf-8")

    if not subject:
        from datetime import date
        subject = f"AICloud Strategist — Daily Status Report — {date.today().isoformat()}"

    recipients = [addr.strip() for addr in to_email.split(",")]

    console.print(f"[bold blue]Sending email via {send_method.upper()}...[/bold blue]")
    console.print(f"  From: {from_email}")
    console.print(f"  To: {', '.join(recipients)}")
    console.print(f"  Subject: {subject}")

    if send_method == "ses":
        from finxcloud.email.sender import send_email_ses
        from finxcloud.auth.credentials import AWSCredentials, create_session

        if access_key and secret_key:
            creds = AWSCredentials(
                access_key_id=access_key,
                secret_access_key=secret_key,
                region=region,
            )
            session = create_session(creds)
        else:
            session = None  # use default boto3 credentials chain

        success = send_email_ses(recipients, subject, html_body, from_email,
                                 region=region, session=session)
    else:
        from finxcloud.email.sender import EmailConfig, send_email

        config = EmailConfig(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            from_address=from_email,
        )
        if not config.is_configured:
            console.print(
                "[red]SMTP not configured.[/red] Set FINXCLOUD_SMTP_HOST, "
                "FINXCLOUD_SMTP_USER, FINXCLOUD_SMTP_PASSWORD, or use --via ses."
            )
            sys.exit(1)
        success = send_email(config, recipients, subject, html_body)

    if success:
        console.print("[green]  ✓ Email sent successfully.[/green]")
    else:
        console.print("[red]  ✗ Failed to send email. Check logs for details.[/red]")
        sys.exit(1)


@main.group()
def schedule() -> None:
    """Manage EC2 instance start/stop schedules."""


@schedule.command("add")
@click.option("--instance-id", required=True, help="EC2 instance ID.")
@click.option("--region", default="us-east-1", help="AWS region of the instance.")
@click.option("--stop-time", required=True, help="Time to stop the instance (HH:MM UTC).")
@click.option("--start-time", required=True, help="Time to start the instance (HH:MM UTC).")
@click.option("--days", default="mon,tue,wed,thu,fri", help="Days to apply schedule (comma-separated).")
@click.option("--account-id", default=None, help="AWS account ID (optional label).")
def schedule_add(
    instance_id: str,
    region: str,
    stop_time: str,
    start_time: str,
    days: str,
    account_id: str | None,
) -> None:
    """Add a new start/stop schedule for an EC2 instance."""
    from finxcloud.scheduler.scheduler import ScheduleManager

    mgr = ScheduleManager()
    day_list = [d.strip().lower() for d in days.split(",")]
    entry = mgr.add_schedule(
        instance_id=instance_id,
        region=region,
        stop_time=stop_time,
        start_time=start_time,
        days=day_list,
        account_id=account_id,
    )
    console.print(f"[green]Schedule added:[/green] {entry['id']}")
    console.print(f"  Instance: {instance_id} ({region})")
    console.print(f"  Stop at {stop_time} UTC, Start at {start_time} UTC")
    console.print(f"  Days: {', '.join(day_list)}")


@schedule.command("list")
def schedule_list() -> None:
    """List all configured schedules."""
    from finxcloud.scheduler.scheduler import ScheduleManager

    mgr = ScheduleManager()
    schedules = mgr.list_schedules()
    if not schedules:
        console.print("[yellow]No schedules configured.[/yellow]")
        return

    table = Table(title="Instance Schedules", border_style="blue")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Instance")
    table.add_column("Region")
    table.add_column("Stop")
    table.add_column("Start")
    table.add_column("Days")
    table.add_column("Enabled")

    for s in schedules:
        table.add_row(
            s["id"],
            s["instance_id"],
            s["region"],
            s["stop_time"],
            s["start_time"],
            ",".join(s.get("days", [])),
            "[green]Yes[/green]" if s.get("enabled") else "[red]No[/red]",
        )
    console.print(table)


@schedule.command("remove")
@click.argument("schedule_id")
def schedule_remove(schedule_id: str) -> None:
    """Remove a schedule by ID."""
    from finxcloud.scheduler.scheduler import ScheduleManager

    mgr = ScheduleManager()
    if mgr.delete_schedule(schedule_id):
        console.print(f"[green]Schedule {schedule_id} removed.[/green]")
    else:
        console.print(f"[red]Schedule {schedule_id} not found.[/red]")
        sys.exit(1)


@schedule.command("run")
@click.option("--access-key", envvar="AWS_ACCESS_KEY_ID", required=True, help="AWS Access Key ID.")
@click.option("--secret-key", envvar="AWS_SECRET_ACCESS_KEY", required=True, help="AWS Secret Access Key.")
@click.option("--session-token", envvar="AWS_SESSION_TOKEN", default=None, help="AWS Session Token.")
@click.option("--region", default="us-east-1", help="Default AWS region.")
def schedule_run(access_key: str, secret_key: str, session_token: str | None, region: str) -> None:
    """Execute any schedules that are due right now."""
    from finxcloud.scheduler.executor import ScheduleExecutor

    creds = AWSCredentials(
        access_key_id=access_key,
        secret_access_key=secret_key,
        session_token=session_token,
        region=region,
    )
    session = create_session(creds)
    executor = ScheduleExecutor(session)
    results = executor.execute_due_actions()

    if not results:
        console.print("[green]No actions due at this time.[/green]")
        return

    for r in results:
        status = "[green]OK[/green]" if r["status"] == "ok" else f"[red]{r.get('error', 'failed')}[/red]"
        console.print(f"  {r['action'].upper()} {r['instance_id']} — {status}")


@main.command()
@click.option("--webhook-url", required=True, help="Webhook URL (Slack or generic HTTP).")
@click.option("--event", default="scan_complete", type=click.Choice(["scan_complete", "anomaly_detected", "budget_threshold"]),
              help="Event type to send.")
@click.option("--message", default=None, help="Custom message text (for testing).")
def notify(webhook_url: str, event: str, message: str | None) -> None:
    """Send a test notification to a webhook URL."""
    from finxcloud.notifications.webhook import NotificationSender

    sender = NotificationSender()
    data = {"message": message or f"Test notification for event: {event}"}

    console.print(f"[bold blue]Sending {event} notification...[/bold blue]")
    result = sender.send_to_url(webhook_url, event, data)

    if result["status"] == "ok":
        console.print(f"[green]  Notification sent successfully (HTTP {result.get('http_status')}).[/green]")
    else:
        console.print(f"[red]  Failed: {result.get('error')}[/red]")
        sys.exit(1)


@main.group()
def webhooks() -> None:
    """Manage webhook configurations."""


@webhooks.command("add")
@click.option("--url", required=True, help="Webhook URL.")
@click.option("--name", default="", help="Friendly name for the webhook.")
@click.option("--type", "wh_type", default="generic", type=click.Choice(["slack", "generic"]), help="Webhook type.")
@click.option("--events", default="scan_complete,anomaly_detected,budget_threshold",
              help="Comma-separated events to subscribe to.")
def webhooks_add(url: str, name: str, wh_type: str, events: str) -> None:
    """Add a new webhook configuration."""
    from finxcloud.notifications.webhook import WebhookConfig

    cfg = WebhookConfig()
    event_list = [e.strip() for e in events.split(",")]
    entry = cfg.add_webhook(url=url, name=name, webhook_type=wh_type, events=event_list)
    console.print(f"[green]Webhook added:[/green] {entry['id']} ({entry['name']})")


@webhooks.command("list")
def webhooks_list() -> None:
    """List all configured webhooks."""
    from finxcloud.notifications.webhook import WebhookConfig

    cfg = WebhookConfig()
    hooks = cfg.list_webhooks()
    if not hooks:
        console.print("[yellow]No webhooks configured.[/yellow]")
        return

    table = Table(title="Configured Webhooks", border_style="blue")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Events")
    table.add_column("Enabled")

    for h in hooks:
        table.add_row(
            h["id"],
            h.get("name", ""),
            h.get("type", "generic"),
            ", ".join(h.get("events", [])),
            "[green]Yes[/green]" if h.get("enabled") else "[red]No[/red]",
        )
    console.print(table)


@webhooks.command("remove")
@click.argument("webhook_id")
def webhooks_remove(webhook_id: str) -> None:
    """Remove a webhook by ID."""
    from finxcloud.notifications.webhook import WebhookConfig

    cfg = WebhookConfig()
    if cfg.delete_webhook(webhook_id):
        console.print(f"[green]Webhook {webhook_id} removed.[/green]")
    else:
        console.print(f"[red]Webhook {webhook_id} not found.[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
