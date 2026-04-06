# FinXCloud — AWS Cost Optimization Tool

A Python CLI tool and web dashboard that scans AWS accounts, analyzes costs, and generates actionable savings recommendations based on the AWS Well-Architected Framework.

## Features

- **Multi-account support**: Standalone accounts and AWS Organizations
- **Full resource scanning**: EC2, EBS, RDS, S3, Lambda, networking (EIPs, NAT GW, ALB/NLB)
- **Cost Explorer integration**: Cost breakdowns by service, region, and account
- **CloudWatch utilization analysis**: CPU, network, and connection metrics
- **Recommendations engine**: Based on AWS Well-Architected Framework cost optimization pillar
- **Phase-wise roadmap**: Quick Wins / Medium Term / Strategic implementation plan
- **Dual output**: JSON + HTML reports
- **Web Dashboard**: Interactive single-page dashboard with charts and live scan trigger

## Requirements

- Python 3.11+
- AWS credentials with read-only access (see [IAM Policy](docs/iam-policy.md))

## Installation

```bash
pip install -e .
```

## Quick Start

### Web Dashboard (Recommended)

```bash
# Install with web dependencies
pip install -e ".[web]"

# Launch the dashboard
finxcloud web

# Opens at http://127.0.0.1:8000
# Default login: admin / admin
```

**Authentication**: The dashboard requires login. Configure credentials via environment variables:

```bash
export FINXCLOUD_ADMIN_USER=admin        # default: admin
export FINXCLOUD_ADMIN_PASS=changeme     # default: admin
export FINXCLOUD_JWT_SECRET=your-secret  # auto-generated if not set
```

The web dashboard provides:
- Live scan trigger with real-time progress
- Cost breakdown charts (by service, region, daily trend)
- Savings opportunity visualization
- Recommendations table with effort levels
- Resource inventory
- Implementation roadmap

Options: `--host` (default: 127.0.0.1), `--port` / `-p` (default: 8000), `--reload` (dev mode).

### Deploy to S3 (Public URL)

Deploy the dashboard to an S3 bucket for public web access:

```bash
# Run a fresh scan and deploy the dashboard to S3
finxcloud deploy \
  --access-key AKIA... \
  --secret-key ... \
  --bucket my-finxcloud-dashboard \
  --region us-east-1

# Or deploy using existing local reports (no new scan)
finxcloud deploy \
  --access-key AKIA... \
  --secret-key ... \
  --bucket my-finxcloud-dashboard \
  --from-reports \
  --report-dir reports
```

This will:
1. Run a scan (or load existing reports with `--from-reports`)
2. Generate a self-contained HTML dashboard with embedded data
3. Create/configure the S3 bucket for static website hosting
4. Upload the dashboard and print the public URL

Add `--deploy-password mysecret` to protect the S3 dashboard with a client-side password gate.

The public URL will be: `http://<bucket>.s3-website-<region>.amazonaws.com`

**Required IAM permissions** for deploy: `s3:CreateBucket`, `s3:PutBucketWebsite`, `s3:PutBucketPolicy`, `s3:PutPublicAccessBlock`, `s3:PutObject`, `s3:HeadBucket` (in addition to the read-only scanning permissions).

### CLI

```bash
# Using environment variables
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
finxcloud scan

# Using command-line options
finxcloud scan --access-key AKIA... --secret-key ... --region us-east-1

# Scan all Organization accounts
finxcloud scan --access-key AKIA... --secret-key ... --org

# Scan specific regions only
finxcloud scan --regions us-east-1,eu-west-1

# Skip CloudWatch utilization checks (faster scan)
finxcloud scan --skip-utilization

# Custom output directory
finxcloud scan -o /path/to/reports

# Verbose logging
finxcloud -v scan --access-key AKIA... --secret-key ...
```

## CLI Options

| Option | Env Var | Default | Description |
|--------|---------|---------|-------------|
| `--access-key` | `AWS_ACCESS_KEY_ID` | required | AWS Access Key ID |
| `--secret-key` | `AWS_SECRET_ACCESS_KEY` | required | AWS Secret Access Key |
| `--session-token` | `AWS_SESSION_TOKEN` | none | Session token for temporary credentials |
| `--region` | | `us-east-1` | Default AWS region |
| `--profile` | | none | AWS CLI profile (overrides key-based auth) |
| `--org/--no-org` | | `--no-org` | Scan all Organization member accounts |
| `--org-role` | | `OrganizationAccountAccessRole` | IAM role to assume in member accounts |
| `--days` | | 30 | Cost analysis lookback period (days) |
| `--regions` | | all | Comma-separated list of regions to scan |
| `--skip-utilization` | | false | Skip CloudWatch utilization checks |
| `-o/--output-dir` | | `reports` | Output directory for reports |
| `-v/--verbose` | | false | Enable debug logging |

## Output

Reports are written to the output directory (default: `reports/`):

| File | Description |
|------|-------------|
| `detailed_report.json` | Full resource inventory and cost breakdown |
| `summary_report.json` | Executive summary with top savings opportunities |
| `roadmap_report.json` | Phase-wise implementation roadmap |
| `report.html` | Single-page HTML report with all findings |

## Recommendations Engine

The tool checks for common cost waste patterns:

| Check | Category | Description |
|-------|----------|-------------|
| Idle EC2 | Compute | Stopped instances, low-CPU instances (<5% avg) |
| Unattached EBS | Storage | EBS volumes not attached to any instance |
| Old Snapshots | Storage | Snapshots older than 90 days |
| Unused EIPs | Networking | Elastic IPs not associated with instances |
| Over-provisioned RDS | Database | RDS instances with low utilization |
| S3 Lifecycle | Storage | Buckets missing lifecycle policies |
| Idle Load Balancers | Networking | ALB/NLB with no targets (flagged for review) |
| Lambda Right-sizing | Compute | Functions with >512MB memory |

Each recommendation includes:
- Estimated monthly savings
- Effort level (low / medium / high)
- Well-Architected Framework pillar reference
- Specific action to take

## Architecture

```
finxcloud/
├── cli.py                    # CLI entry point (Click)
├── auth/
│   ├── credentials.py        # AWS credential management
│   └── organizations.py      # Organizations account discovery
├── scanner/
│   ├── base.py               # Scanner base class with retry logic
│   ├── ec2.py                # EC2, EBS, snapshots, AMIs
│   ├── rds.py                # RDS instances and snapshots
│   ├── s3.py                 # S3 buckets and config
│   ├── lambda_.py            # Lambda functions
│   ├── networking.py         # EIPs, NAT GW, load balancers
│   └── opensearch.py         # OpenSearch domains
├── analyzer/
│   ├── cost_explorer.py      # AWS Cost Explorer integration
│   ├── utilization.py        # CloudWatch metrics analysis
│   └── recommendations.py    # Well-Architected recommendations engine
├── reporter/
│   ├── detailed.py           # Full resource-level report
│   ├── summary.py            # Executive summary
│   └── roadmap.py            # Phase-wise implementation plan
├── output/
│   ├── json_writer.py        # JSON report writer
│   └── html_writer.py        # HTML report generator
└── web/
    ├── app.py                # FastAPI backend
    └── static/
        └── index.html        # Dashboard frontend (Chart.js)
```

## License

Proprietary — AICloud Strategist
