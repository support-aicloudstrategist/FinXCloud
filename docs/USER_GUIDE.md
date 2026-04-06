# FinXCloud — Complete User Guide

End-to-end instructions for scanning AWS accounts and generating cost optimization reports.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [AWS Account Setup](#3-aws-account-setup)
4. [Running Your First Scan](#4-running-your-first-scan)
5. [Understanding the Reports](#5-understanding-the-reports)
6. [Using the Web Dashboard](#6-using-the-web-dashboard)
7. [Adding a New AWS Account](#7-adding-a-new-aws-account)
8. [Scanning AWS Organizations](#8-scanning-aws-organizations)
9. [Sending Reports via Email](#9-sending-reports-via-email)
10. [Deploying the Dashboard (Public URL)](#10-deploying-the-dashboard-public-url)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

- **Python 3.11 or higher** — [Download Python](https://www.python.org/downloads/)
- **pip** — comes with Python
- **An AWS account** with programmatic access (Access Key + Secret Key)
- **Git** (optional, for cloning the repo)

Verify your Python version:

```bash
python3 --version
# Should show Python 3.11.x or higher
```

---

## 2. Installation

### Option A: Clone from GitHub

```bash
git clone https://github.com/support-aicloudstrategist/FinXCloud.git
cd FinXCloud
pip install -e .
```

### Option B: Install directly

```bash
pip install -e "git+https://github.com/support-aicloudstrategist/FinXCloud.git#egg=finxcloud"
```

Verify the installation:

```bash
finxcloud --help
```

You should see:

```
Usage: finxcloud [OPTIONS] COMMAND [ARGS]...

  FinXCloud — AWS Cost Optimization Tool

Options:
  -v, --verbose  Enable debug logging.
  --help         Show this message and exit.

Commands:
  deploy       Deploy the FinXCloud dashboard to S3 with a public URL.
  scan         Scan AWS resources and generate cost optimization reports.
  send-report  Send a report email via AWS SES API or SMTP.
  web          Launch the FinXCloud web dashboard.
```

---

## 3. AWS Account Setup

### Step 1: Create an IAM User

1. Log in to the [AWS Console](https://console.aws.amazon.com/)
2. Go to **IAM** > **Users** > **Create user**
3. Name it `FinXCloud` (or any name you prefer)
4. Select **Programmatic access**

### Step 2: Attach the Required IAM Policy

Create a custom policy with these permissions (read-only access for scanning):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FinXCloudReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeSnapshots",
        "ec2:DescribeImages",
        "ec2:DescribeAddresses",
        "ec2:DescribeNatGateways",
        "ec2:DescribeRegions",
        "rds:DescribeDBInstances",
        "rds:DescribeDBSnapshots",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "s3:GetLifecycleConfiguration",
        "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "lambda:ListFunctions",
        "lambda:GetFunction",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
        "es:ListDomainNames",
        "es:DescribeDomains",
        "cloudwatch:GetMetricStatistics",
        "ce:GetCostAndUsage",
        "organizations:ListAccounts",
        "organizations:DescribeOrganization",
        "sts:GetCallerIdentity",
        "sts:AssumeRole"
      ],
      "Resource": "*"
    }
  ]
}
```

### Step 3: Create Access Keys

1. In IAM, select your user > **Security credentials** tab
2. Click **Create access key**
3. Select **Command Line Interface (CLI)**
4. Save the **Access Key ID** and **Secret Access Key** securely

> **Security note:** Never share your access keys in public channels. Use environment variables or AWS profiles to manage them.

---

## 4. Running Your First Scan

### Method 1: Using Environment Variables (Recommended)

```bash
export AWS_ACCESS_KEY_ID=AKIA...your-key...
export AWS_SECRET_ACCESS_KEY=...your-secret...

finxcloud scan
```

### Method 2: Using Command-Line Flags

```bash
finxcloud scan \
  --access-key AKIA...your-key... \
  --secret-key ...your-secret... \
  --region us-east-1
```

### Method 3: Using an AWS CLI Profile

If you have the AWS CLI configured with profiles:

```bash
finxcloud scan --profile my-profile
```

### What Happens During a Scan

The tool will:

1. **Validate credentials** — confirms your AWS identity
2. **Scan resources** — discovers EC2 instances, EBS volumes, RDS, S3 buckets, Lambda functions, networking resources, and OpenSearch domains
3. **Pull Cost Explorer data** — retrieves 30-day cost breakdowns by service, region, and account
4. **Analyze utilization** — checks CloudWatch metrics for right-sizing opportunities
5. **Generate recommendations** — identifies cost savings based on the AWS Well-Architected Framework
6. **Build reports** — creates JSON and HTML reports in the `reports/` directory

### Scan Output

After the scan completes, you will see:

```
FinXCloud Scan Complete
  Account: 123456789012 (arn:aws:iam::123456789012:user/FinXCloud)
  Resources scanned: 21
  Reports:
    detailed_report.json
    summary_report.json
    roadmap_report.json
    finxcloud_report.html
```

Reports are saved to the `reports/` directory (configurable with `-o`).

### Common Scan Options

```bash
# Scan specific regions only
finxcloud scan --regions us-east-1,ap-south-1

# Skip CloudWatch checks (faster scan)
finxcloud scan --skip-utilization

# Change lookback period for cost analysis
finxcloud scan --days 60

# Custom output directory
finxcloud scan -o /path/to/reports

# Enable verbose logging
finxcloud -v scan
```

---

## 5. Understanding the Reports

### Report Files

| File | Description |
|------|-------------|
| `summary_report.json` | Executive summary: total cost, savings potential, top recommendations |
| `detailed_report.json` | Full resource inventory with cost breakdown by service/region/account |
| `roadmap_report.json` | Phase-wise savings implementation plan (Quick Wins, Medium Term, Strategic) |
| `finxcloud_report.html` | Visual HTML report — open in any browser |

### Key Metrics

- **Total Resources** — number of AWS resources discovered
- **30-Day Cost** — total spend from AWS Cost Explorer
- **Potential Savings** — estimated monthly savings from all recommendations
- **Savings Percentage** — potential savings as a percentage of total cost
- **Quick Wins** — number of low-effort, high-impact recommendations

### Recommendation Categories

| Category | What It Checks |
|----------|----------------|
| Idle EC2 Instances | Stopped instances still incurring EBS costs |
| Unattached EBS Volumes | Volumes not attached to any instance |
| Old EBS Snapshots | Snapshots older than 90 days |
| Unused Elastic IPs | EIPs not associated with running instances |
| Over-provisioned RDS | RDS instances with low CPU utilization |
| S3 Lifecycle Gaps | Buckets without lifecycle rules for cost-effective storage tiering |
| Idle Load Balancers | ALB/NLB with zero healthy targets |
| Lambda Right-sizing | Functions allocated more than 512MB memory |
| OpenSearch Domains | Domain sizing and configuration optimization |

---

## 6. Using the Web Dashboard

### Start the Dashboard Locally

```bash
# Install with web dependencies
pip install -e .

# Launch the dashboard
python -m finxcloud.web.app
```

Open http://localhost:8000 in your browser.

### Login

- **Username:** `admin`
- **Password:** `admin`

To change the default credentials:

```bash
export FINXCLOUD_ADMIN_USER=your_username
export FINXCLOUD_ADMIN_PASS=your_password
python -m finxcloud.web.app
```

### Running a Scan from the Dashboard

1. Enter your AWS Access Key and Secret Key in the form
2. Select the default region
3. Optionally check "Scan all Organization accounts"
4. Click **Start Scan**
5. Wait for the scan to complete (typically 1-3 minutes)
6. The dashboard will display interactive charts and recommendations

---

## 7. Adding a New AWS Account

To scan a different AWS account, simply provide that account's credentials:

### Option A: Different Access Keys

```bash
# Account 1
finxcloud scan --access-key AKIA_ACCOUNT1_KEY --secret-key SECRET1

# Account 2
finxcloud scan --access-key AKIA_ACCOUNT2_KEY --secret-key SECRET2 -o reports/account2
```

### Option B: AWS CLI Profiles

Set up multiple profiles in `~/.aws/credentials`:

```ini
[account1]
aws_access_key_id = AKIA...
aws_secret_access_key = ...

[account2]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

Then scan each profile:

```bash
finxcloud scan --profile account1 -o reports/account1
finxcloud scan --profile account2 -o reports/account2
```

### Option C: Cross-Account Roles (Best Practice)

If you use AWS Organizations, set up a single IAM user in the management account and use cross-account roles:

1. Create the IAM user in the management account
2. In each member account, create a role (e.g., `FinXCloudReadOnly`) with the read-only policy above
3. Add a trust policy allowing the management account to assume the role
4. Run with the `--org` flag (see next section)

---

## 8. Scanning AWS Organizations

If your AWS account is the management account of an Organization:

```bash
finxcloud scan \
  --access-key AKIA... \
  --secret-key ... \
  --org
```

This will:

1. List all member accounts in the Organization
2. Assume the `OrganizationAccountAccessRole` in each member account
3. Scan all accounts and merge the results
4. Generate a consolidated report across all accounts

### Custom Cross-Account Role

If your member accounts use a different role name:

```bash
finxcloud scan --org --org-role MyCustomReadOnlyRole
```

### Prerequisites for Organization Scanning

- The IAM user must be in the **management (root) account**
- The user needs `organizations:ListAccounts` and `sts:AssumeRole` permissions
- Each member account must have the cross-account role with a trust policy

---

## 9. Sending Reports via Email

### Method 1: AWS SES (Recommended)

Send the HTML report via AWS Simple Email Service:

```bash
finxcloud send-report \
  --to support@aicloudstrategist.com \
  --from-email noreply@aicloudstrategist.com \
  --report-file reports/finxcloud_report.html \
  --via ses \
  --access-key AKIA... \
  --secret-key ... \
  --region us-east-1
```

**SES Setup Required:**

1. Go to AWS Console > **SES** > **Verified identities**
2. Verify the sender email address (or domain)
3. If your SES account is in **sandbox mode**, also verify the recipient email
4. Add `ses:SendEmail` permission to your IAM user:

```json
{
  "Effect": "Allow",
  "Action": ["ses:SendEmail", "ses:VerifyEmailIdentity", "ses:GetIdentityVerificationAttributes"],
  "Resource": "*"
}
```

### Method 2: SMTP

Send via any SMTP server (Gmail, Outlook, your own mail server):

```bash
finxcloud send-report \
  --to support@aicloudstrategist.com \
  --from-email your-email@gmail.com \
  --report-file reports/finxcloud_report.html \
  --via smtp \
  --smtp-host smtp.gmail.com \
  --smtp-port 587 \
  --smtp-user your-email@gmail.com \
  --smtp-password your-app-password
```

> **Gmail note:** Use an [App Password](https://myaccount.google.com/apppasswords), not your regular password.

### Using Environment Variables (Recommended for Automation)

```bash
export FINXCLOUD_FROM_EMAIL=noreply@aicloudstrategist.com
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...

finxcloud send-report \
  --to support@aicloudstrategist.com \
  --report-file reports/finxcloud_report.html \
  --via ses
```

---

## 10. Deploying the Dashboard (Public URL)

### Option A: GitHub Pages (Free)

The dashboard is already live at:
**https://support-aicloudstrategist.github.io/FinXCloud/**

To update with fresh scan data:

1. Run a new scan: `finxcloud scan`
2. The dashboard will be rebuilt and pushed automatically

### Option B: S3 Static Website

Deploy to an S3 bucket:

```bash
finxcloud deploy \
  --access-key AKIA... \
  --secret-key ... \
  --bucket finxcloud-dashboard \
  --region us-east-1
```

With password protection:

```bash
finxcloud deploy \
  --access-key AKIA... \
  --secret-key ... \
  --bucket finxcloud-dashboard \
  --deploy-password your-password
```

Using existing reports (no new scan):

```bash
finxcloud deploy \
  --access-key AKIA... \
  --secret-key ... \
  --bucket finxcloud-dashboard \
  --from-reports \
  --report-dir reports
```

**Required IAM permissions** for S3 deploy:

```json
{
  "Effect": "Allow",
  "Action": [
    "s3:PutObject",
    "s3:PutBucketWebsite",
    "s3:PutBucketPolicy",
    "s3:PutPublicAccessBlock",
    "s3:CreateBucket",
    "s3:GetBucketLocation"
  ],
  "Resource": ["arn:aws:s3:::finxcloud-dashboard", "arn:aws:s3:::finxcloud-dashboard/*"]
}
```

---

## 11. Troubleshooting

### "Access Denied" errors during scan

Your IAM user is missing required permissions. Attach the full read-only policy from [Section 3](#step-2-attach-the-required-iam-policy).

### "Cost Explorer is not enabled"

AWS Cost Explorer must be enabled in your account. Go to AWS Console > **Billing** > **Cost Explorer** > **Enable Cost Explorer**. It takes 24 hours to start collecting data.

### Scan returns 0 resources

Check that you're scanning the correct region. By default, the tool scans all regions. Use `--regions us-east-1,ap-south-1` to target specific regions.

### "OrganizationAccountAccessRole" errors with --org

Each member account needs a role with this exact name (or use `--org-role` to specify a different name). The role must have a trust policy allowing the management account to assume it.

### Email sending fails

- **SES:** Ensure the sender email is verified in SES. If in sandbox mode, the recipient must also be verified.
- **SMTP:** Verify the host, port, username, and password. For Gmail, use an App Password.

### Dashboard shows "Connection error"

The Web UI dashboard (local mode) requires the FastAPI backend to be running. Start it with:

```bash
python -m finxcloud.web.app
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Scan (single account) | `finxcloud scan --access-key ... --secret-key ...` |
| Scan (all org accounts) | `finxcloud scan --access-key ... --secret-key ... --org` |
| Start Web Dashboard | `python -m finxcloud.web.app` |
| Deploy to S3 | `finxcloud deploy --access-key ... --secret-key ... --bucket ...` |
| Send report via email | `finxcloud send-report --to email@... --from-email ... --report-file ... --via ses` |
| View HTML report | Open `reports/finxcloud_report.html` in a browser |

---

*FinXCloud by AICloud Strategist*
